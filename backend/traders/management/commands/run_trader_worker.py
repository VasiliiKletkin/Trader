"""
Stateful event-driven обработка трейдеров.

Держит трейдеров и exchange_client соединения в памяти.
Подписывается на Redis Pub/Sub candle:* для мгновенной обработки.
Каждые 10 минут: reconcile трейдеров из БД + sync состояния в БД.

Использование:
  python manage.py run_trader_worker
"""

import asyncio
import contextlib
import json
import signal
from collections import defaultdict

import redis.asyncio as aioredis
from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand
from loguru import logger

from exchange_clients.domain import AbstractExchangeClient
from exchanges.domain import ExchangeCandle as DomainExchangeCandle
from telegram_bots.tasks import send_notification
from traders.domain import Trader as DomainTrader
from traders.models import Trader, TraderError
from traders.schemas import TraderStatus

ACTIVE_STATUSES = [
    TraderStatus.ENABLED,
    TraderStatus.PAUSED,
    TraderStatus.ERROR,
]

RECONCILE_INTERVAL = 600  # 10 минут


class TraderWorker:
    """Stateful worker: держит трейдеров и соединения в памяти."""

    def __init__(self):
        self.shutdown_event = asyncio.Event()
        # trader_id → (ORM Trader, Domain Trader)
        self._traders: dict[int, tuple[Trader, DomainTrader]] = {}
        # exchange_client_id → Domain ExchangeClient (подключённый)
        self._clients: dict[int, AbstractExchangeClient] = {}
        # (exchange_name, symbol, timeframe) → set[trader_id]
        self._subscriptions: dict[tuple[str, str, str], set[int]] = defaultdict(set)

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_signal)

        # Первоначальная загрузка
        await self._reconcile()

        # Запускаем параллельные циклы
        reconcile_task = asyncio.create_task(self._reconcile_loop())
        pubsub_task = asyncio.create_task(self._pubsub_loop())

        await self.shutdown_event.wait()

        # Graceful shutdown
        reconcile_task.cancel()
        pubsub_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(reconcile_task, pubsub_task)

        await self._sync_all()
        await self._close_all_clients()
        logger.info("TraderWorker завершён.")

    def _handle_signal(self) -> None:
        logger.info("Получен сигнал завершения...")
        self.shutdown_event.set()

    # --- Pub/Sub ---

    async def _pubsub_loop(self) -> None:
        redis_settings = settings.REDIS
        redis = aioredis.Redis(
            host=str(redis_settings["HOST"]),
            port=int(redis_settings["PORT"]),
            db=int(redis_settings["EXCHANGE_CACHE_DATABASE"]),
            password=str(redis_settings["PASSWORD"]) or None,
        )
        pubsub = redis.pubsub()
        await pubsub.psubscribe("candle:*")
        logger.info("Подписан на candle:*")

        try:
            while not self.shutdown_event.is_set():
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if message is None:
                    continue

                channel = message["channel"].decode()
                parts = channel.split(":")
                if len(parts) != 4:
                    continue

                _, exchange_name, symbol, timeframe = parts
                key = (exchange_name, symbol, timeframe)

                trader_ids = self._subscriptions.get(key)
                if not trader_ids:
                    continue

                candle_data = json.loads(message["data"])
                candle = DomainExchangeCandle(**candle_data)

                for trader_id in list(trader_ids):
                    entry = self._traders.get(trader_id)
                    if entry is None:
                        continue
                    _, domain_trader = entry
                    try:
                        await domain_trader.handle_candle(candle=candle)
                    except Exception as e:
                        await self._on_trader_error(trader_id, e)
        finally:
            await pubsub.punsubscribe("candle:*")
            await pubsub.close()
            await redis.close()

    # --- Reconcile ---

    async def _reconcile_loop(self) -> None:
        while not self.shutdown_event.is_set():
            await asyncio.sleep(RECONCILE_INTERVAL)
            await self._sync_all()
            await self._reconcile()

    async def _reconcile(self) -> None:
        """Загружает трейдеров из БД, добавляет новых, удаляет неактивных."""
        desired = await self._load_desired_traders()

        desired_ids = set(desired.keys())
        current_ids = set(self._traders.keys())

        # Удаляем неактивных
        for tid in current_ids - desired_ids:
            self._remove_trader(tid)

        # Добавляем новых
        for tid in desired_ids - current_ids:
            orm_trader = desired[tid]
            await self._add_trader(orm_trader)

        # Закрываем неиспользуемые клиенты
        await self._cleanup_clients()

        logger.info(
            f"Reconcile: {len(self._traders)} трейдеров, {len(self._clients)} клиентов"
        )

    @sync_to_async
    def _load_desired_traders(self) -> dict[int, Trader]:
        return {
            t.pk: t
            for t in Trader.objects.filter(
                status__in=ACTIVE_STATUSES,
            ).select_related(
                "exchange_client",
                "exchange_client__exchange",
                "exchange_client__proxy",
                "candle_source",
                "candle_source__trading_pair",
                "candle_source__exchange_client",
                "candle_source__exchange_client__exchange",
                "risk_manager",
                "strategy",
            )
        }

    async def _add_trader(self, orm_trader: Trader) -> None:
        """Добавляет трейдера: подключает клиента, instantiate, load."""
        ec_id = orm_trader.exchange_client_id

        # Подключаем клиента если нужно
        if ec_id not in self._clients:
            domain_client = orm_trader.exchange_client.instantiate()
            await domain_client.__aenter__()
            self._clients[ec_id] = domain_client
            logger.info(f"Подключён exchange_client_id={ec_id}")

        domain_trader = orm_trader.instantiate(
            domain_exchange_client=self._clients[ec_id],
        )
        await sync_to_async(orm_trader.load)(trader=domain_trader)

        self._traders[orm_trader.pk] = (orm_trader, domain_trader)

        # Индекс для маршрутизации свечей
        cs = orm_trader.candle_source
        key = (
            cs.exchange_client.exchange.name,
            cs.trading_pair.name,
            cs.timeframe,
        )
        self._subscriptions[key].add(orm_trader.pk)

        logger.info(f"Добавлен трейдер #{orm_trader.pk}: {orm_trader}")

    def _remove_trader(self, trader_id: int) -> None:
        """Удаляет трейдера из памяти и индекса."""
        entry = self._traders.pop(trader_id, None)
        if entry is None:
            return

        # Убираем из индекса подписок
        for key, ids in list(self._subscriptions.items()):
            ids.discard(trader_id)
            if not ids:
                del self._subscriptions[key]

        logger.info(f"Удалён трейдер #{trader_id}")

    async def _cleanup_clients(self) -> None:
        """Закрывает клиентов без трейдеров."""
        used_ec_ids = {orm.exchange_client_id for orm, _ in self._traders.values()}
        for ec_id in set(self._clients) - used_ec_ids:
            client = self._clients.pop(ec_id)
            with contextlib.suppress(Exception):
                await client.__aexit__(None, None, None)
            logger.info(f"Отключён exchange_client_id={ec_id}")

    # --- Sync ---

    async def _sync_all(self) -> None:
        """Сохраняет состояние всех трейдеров в БД."""
        if not self._traders:
            return

        @sync_to_async
        def _do_sync():
            for orm_trader, domain_trader in self._traders.values():
                try:
                    orm_trader.sync(trader=domain_trader)
                except Exception as e:
                    logger.error(f"Ошибка sync трейдера #{orm_trader.pk}: {e}")

        await _do_sync()
        logger.info(f"Sync: {len(self._traders)} трейдеров")

    # --- Errors ---

    async def _on_trader_error(self, trader_id: int, error: Exception) -> None:
        entry = self._traders.get(trader_id)
        if entry is None:
            return
        orm_trader, _ = entry
        error_type = type(error).__name__
        logger.error(f"Ошибка трейдера #{trader_id} [{error_type}]: {error}")

        @sync_to_async
        def _save_error():
            TraderError.objects.create(
                trader=orm_trader,
                message=str(error),
                type=error_type,
            )

        await _save_error()
        send_notification.delay(
            message=(f"Ошибка trader worker: {orm_trader}\n[{error_type}]: {error}"),
        )

    # --- Shutdown ---

    async def _close_all_clients(self) -> None:
        for ec_id, client in self._clients.items():
            with contextlib.suppress(Exception):
                await client.__aexit__(None, None, None)
            logger.info(f"Отключён exchange_client_id={ec_id}")
        self._clients.clear()
        self._traders.clear()
        self._subscriptions.clear()


class Command(BaseCommand):
    help = "Stateful event-driven обработка трейдеров"

    def handle(self, *args, **options):
        self.stdout.write("Запуск TraderWorker...")
        worker = TraderWorker()
        asyncio.run(worker.run())
