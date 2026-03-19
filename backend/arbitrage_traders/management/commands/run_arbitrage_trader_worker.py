"""
Stateful event-driven обработка арбитражных трейдеров.

Держит трейдеров и exchange_client соединения в памяти.
Подписывается на Redis Pub/Sub arb_candle:* — получает уже спаренные свечи
от ArbitrageCandleProvider.
Каждые 10 минут: reconcile трейдеров из БД + sync состояния в БД.

Использование:
  python manage.py run_arbitrage_trader_worker
"""

import asyncio
import contextlib
import json
import signal

import redis.asyncio as aioredis
from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand
from loguru import logger

from arbitrage_traders.domain import ArbitrageTrader as DomainArbitrageTrader
from arbitrage_traders.domain.schemas import ArbitrageCandle
from arbitrage_traders.models import ArbitrageTrader, ArbitrageTraderError
from arbitrage_traders.schemas import ArbitrageTraderStatus
from exchange_clients.domain import AbstractExchangeClient
from exchanges.domain import ExchangeCandle as DomainExchangeCandle
from telegram_bots.tasks import send_notification

ACTIVE_STATUSES = [
    ArbitrageTraderStatus.ENABLED,
    ArbitrageTraderStatus.PAUSED,
    ArbitrageTraderStatus.ERROR,
]

RECONCILE_INTERVAL = 60 * 10  # 10 минут


class ArbitrageTraderWorker:
    """Stateful worker: держит арбитражных трейдеров и соединения в памяти.

    Подписан на arb_candle:* — получает готовые пары свечей
    от ArbitrageCandleProvider, без собственного паринга.
    """

    def __init__(self):
        self.shutdown_event = asyncio.Event()
        # trader_id → (ORM ArbitrageTrader, Domain ArbitrageTrader)
        self._traders: dict[int, tuple[ArbitrageTrader, DomainArbitrageTrader]] = {}
        # exchange_client_id → Domain ExchangeClient (подключённый)
        self._clients: dict[int, AbstractExchangeClient] = {}

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
        logger.info("ArbitrageTraderWorker завершён.")

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
        provider_candle = redis.pubsub()
        await provider_candle.psubscribe("arb_candle:*")
        logger.info("Подписан на arb_candle:*")

        try:
            while not self.shutdown_event.is_set():
                message = await provider_candle.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if message is None:
                    continue

                # Канал: arb_candle:{trader_id}
                channel = message["channel"].decode()
                parts = channel.split(":")
                if len(parts) != 2:
                    continue

                trader_id = int(parts[1])
                entry = self._traders.get(trader_id)
                if entry is None:
                    continue

                paired_data = json.loads(message["data"])
                left_candle = DomainExchangeCandle(**paired_data["left"])
                right_candle = DomainExchangeCandle(**paired_data["right"])

                _, domain_trader = entry
                arb_candle = ArbitrageCandle(
                    left=left_candle,
                    right=right_candle,
                )
                try:
                    await domain_trader.handle_candle(candle=arb_candle)
                except Exception as e:
                    await self._on_trader_error(trader_id, e)
        finally:
            await provider_candle.punsubscribe("arb_candle:*")
            await provider_candle.close()
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
            f"Reconcile: {len(self._traders)} арбитражных трейдеров, "
            f"{len(self._clients)} клиентов"
        )

    @sync_to_async
    def _load_desired_traders(self) -> dict[int, ArbitrageTrader]:
        return {
            t.pk: t
            for t in ArbitrageTrader.objects.filter(
                status__in=ACTIVE_STATUSES,
            ).select_related(
                "left_exchange_client",
                "left_exchange_client__exchange",
                "left_exchange_client__proxy",
                "right_exchange_client",
                "right_exchange_client__exchange",
                "right_exchange_client__proxy",
                "left_candle_source",
                "left_candle_source__trading_pair",
                "left_candle_source__exchange_client",
                "left_candle_source__exchange_client__exchange",
                "right_candle_source",
                "right_candle_source__trading_pair",
                "right_candle_source__exchange_client",
                "right_candle_source__exchange_client__exchange",
                "risk_manager",
                "strategy",
            )
        }

    async def _add_trader(self, orm_trader: ArbitrageTrader) -> None:
        """Добавляет арбитражного трейдера: подключает клиентов, instantiate, load."""
        left_ec_id = orm_trader.left_exchange_client_id
        right_ec_id = orm_trader.right_exchange_client_id

        # Подключаем клиентов если нужно
        for ec_id, ec_orm in [
            (left_ec_id, orm_trader.left_exchange_client),
            (right_ec_id, orm_trader.right_exchange_client),
        ]:
            if ec_id not in self._clients:
                domain_client = ec_orm.instantiate()
                await domain_client.__aenter__()
                self._clients[ec_id] = domain_client
                logger.info(f"Подключён exchange_client_id={ec_id}")

        domain_trader = orm_trader.instantiate(
            domain_left_exchange_client=self._clients[left_ec_id],
            domain_right_exchange_client=self._clients[right_ec_id],
        )
        await sync_to_async(orm_trader.load)(trader=domain_trader)

        self._traders[orm_trader.pk] = (orm_trader, domain_trader)
        logger.info(f"Добавлен арбитражный трейдер #{orm_trader.pk}: {orm_trader}")

    def _remove_trader(self, trader_id: int) -> None:
        """Удаляет трейдера из памяти."""
        self._traders.pop(trader_id, None)
        logger.info(f"Удалён арбитражный трейдер #{trader_id}")

    async def _cleanup_clients(self) -> None:
        """Закрывает клиентов без трейдеров."""
        used_ec_ids: set[int] = set()
        for orm, _ in self._traders.values():
            used_ec_ids.add(orm.left_exchange_client_id)
            used_ec_ids.add(orm.right_exchange_client_id)

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
                    logger.error(
                        f"Ошибка sync арбитражного трейдера #{orm_trader.pk}: {e}"
                    )

        await _do_sync()
        logger.info(f"Sync: {len(self._traders)} арбитражных трейдеров")

    # --- Errors ---

    async def _on_trader_error(self, trader_id: int, error: Exception) -> None:
        entry = self._traders.get(trader_id)
        if entry is None:
            return
        orm_trader, _ = entry
        error_type = type(error).__name__
        logger.error(
            f"Ошибка арбитражного трейдера #{trader_id} [{error_type}]: {error}"
        )

        @sync_to_async
        def _save_error():
            ArbitrageTraderError.objects.create(
                trader=orm_trader,
                message=str(error),
                type=error_type,
            )

        await _save_error()
        send_notification.delay(
            message=(
                f"Ошибка arbitrage trader worker: {orm_trader}\n[{error_type}]: {error}"
            ),
        )

    # --- Shutdown ---

    async def _close_all_clients(self) -> None:
        for ec_id, client in self._clients.items():
            with contextlib.suppress(Exception):
                await client.__aexit__(None, None, None)
            logger.info(f"Отключён exchange_client_id={ec_id}")
        self._clients.clear()
        self._traders.clear()


class Command(BaseCommand):
    help = "Stateful event-driven обработка арбитражных трейдеров"

    def handle(self, *args, **options):
        self.stdout.write("Запуск ArbitrageTraderWorker...")
        worker = ArbitrageTraderWorker()
        asyncio.run(worker.run())
