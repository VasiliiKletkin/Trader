import asyncio
import contextlib
import signal
from collections.abc import Callable, Coroutine

from loguru import logger

from candle_sources.domain.candle_sources import CandleSource
from candle_sources.domain.ws.streams import OHLCVStream
from exchange_clients.domain import AbstractExchangeClient


class WebSocketStreamManager:
    """
    Менеджер WebSocket стримов с динамической синхронизацией подписок.

    Все операции с БД инжектируются через колбэки.

    Периодически (каждые sync_interval секунд) загружает подписки из БД
    и добавляет/удаляет стримы без перезапуска.
    """

    def __init__(
        self,
        load_subscriptions: Callable[..., Coroutine],
        on_candle: Callable[..., Coroutine],
        on_error: Callable[..., Coroutine],
        sync_interval: int = 30,
    ):
        self.load_subscriptions = load_subscriptions
        self.on_candle = on_candle
        self.on_error = on_error
        self.sync_interval = sync_interval
        self.shutdown_event = asyncio.Event()

        # source_id → asyncio.Task (один стрим на подписку)
        self._streams: dict[int, asyncio.Task] = {}
        # source_id → exchange_client (для закрытия при удалении)
        self._clients: dict[int, AbstractExchangeClient] = {}

    async def run(self) -> None:
        logger.info("WebSocketStreamManager запускается...")

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_signal)

        # Первичная загрузка подписок
        subscriptions = await self.load_subscriptions()
        await self._reconcile(subscriptions)

        if not self._streams:
            logger.warning("Нет активных WS-подписок.")

        # Запускаем цикл синхронизации
        sync_task = asyncio.create_task(self._sync_loop())

        # Ждём завершения (shutdown_event)
        await self.shutdown_event.wait()

        sync_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sync_task

        # Останавливаем все стримы
        for task in self._streams.values():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(*self._streams.values())

        # Закрываем все exchange-клиенты
        for client in self._clients.values():
            with contextlib.suppress(Exception):
                await client.__aexit__(None, None, None)

        logger.info("WebSocketStreamManager завершён.")

    def _handle_signal(self) -> None:
        logger.info("Получен сигнал завершения, останавливаем стримы...")
        self.shutdown_event.set()

    async def _sync_loop(self) -> None:
        """Периодически загружает подписки из БД и синхронизирует стримы."""
        while not self.shutdown_event.is_set():
            await asyncio.sleep(self.sync_interval)
            subscriptions = await self.load_subscriptions()
            await self._reconcile(subscriptions)

    async def _reconcile(self, subscriptions: list[CandleSource]) -> None:
        """Сравнивает текущие стримы с новыми подписками, добавляет/удаляет."""
        sub_by_id = {sub.source_id: sub for sub in subscriptions}
        new_ids = set(sub_by_id.keys())
        current_ids = set(self._streams.keys())

        removed = current_ids - new_ids
        added = new_ids - current_ids

        # Удаляем стримы, которых больше нет в БД
        for source_id in removed:
            logger.info(f"Удаляем стрим source_id={source_id}")
            self._streams[source_id].cancel()
            del self._streams[source_id]
            exchange_client = self._clients.pop(source_id, None)
            if exchange_client:
                with contextlib.suppress(Exception):
                    await exchange_client.__aexit__(None, None, None)

        # Добавляем новые стримы
        for source_id in added:
            sub = sub_by_id[source_id]
            logger.info(
                f"Добавляем стрим source_id={source_id} "
                f"{sub.trading_pair.symbol}:{sub.timeframe.value}"
            )
            await sub.exchange_client.__aenter__()
            self._clients[source_id] = sub.exchange_client

            task = asyncio.create_task(
                OHLCVStream(
                    exchange_client=sub.exchange_client,
                    trading_pair=sub.trading_pair,
                    timeframe=sub.timeframe,
                    on_candle=self.on_candle,
                    on_error=self.on_error,
                    shutdown_event=self.shutdown_event,
                    source_id=source_id,
                ).run(),
                name=f"ohlcv:{sub.trading_pair.symbol}:{sub.timeframe.value}",
            )
            self._streams[source_id] = task

        if removed:
            logger.info(f"Удалено {len(removed)} стримов")
        if added:
            logger.info(f"Добавлено {len(added)} стримов")
