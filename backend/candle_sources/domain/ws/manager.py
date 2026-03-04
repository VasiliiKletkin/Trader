import asyncio
import contextlib
import signal
from collections import defaultdict
from collections.abc import Callable, Coroutine
from typing import Any

import ccxt.pro as ccxtpro
from loguru import logger

from candle_sources.domain.ws.schemas import ExchangeConfig, SubscriptionConfig
from candle_sources.domain.ws.streams import OHLCVStream

# Маппинг class_name → ccxt.pro exchange id
CLASS_NAME_TO_CCXT_PRO: dict[str, str] = {
    "ByBitExchangeClient": "bybit",
    "BinanceExchangeClient": "binance",
    "OKXExchangeClient": "okx",
    "KrakenExchangeClient": "krakenfutures",
    "KuCoinExchangeClient": "kucoinfutures",
    "BitgetExchangeClient": "bitget",
    "BitfinexExchangeClient": "bitfinex",
    "BitMEXExchangeClient": "bitmex",
    "CoinbaseExchangeClient": "coinbase",
    "CoinExExchangeClient": "coinex",
    "DeribitExchangeClient": "deribit",
    "GateIOExchangeClient": "gateio",
    "HTXExchangeClient": "htx",
    "HyperliquidExchangeClient": "hyperliquid",
    "MEXCExchangeClient": "mexc",
    "ParadexExchangeClient": "paradex",
    "PhemexExchangeClient": "phemex",
    "WooFiProExchangeClient": "woofipro",
}


class WebSocketStreamManager:
    """
    Менеджер WebSocket стримов.

    Чистый Python — не зависит от Django.
    Все операции с БД инжектируются через колбэки on_candle / on_error.
    """

    def __init__(
        self,
        subscriptions: list[SubscriptionConfig],
        on_candle: Callable[..., Coroutine],
        on_error: Callable[..., Coroutine],
    ):
        self.subscriptions = subscriptions
        self.on_candle = on_candle
        self.on_error = on_error
        self.shutdown_event = asyncio.Event()
        self.tasks: list[asyncio.Task] = []

    async def run(self) -> None:
        logger.info("WebSocketStreamManager запускается...")

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_signal)

        if not self.subscriptions:
            logger.warning("Нет активных WS-подписок. Завершение.")
            return

        # Группируем подписки по ExchangeConfig (хэшируемый dataclass)
        groups: dict[ExchangeConfig, list[SubscriptionConfig]] = defaultdict(list)
        for sub in self.subscriptions:
            groups[sub.exchange_config].append(sub)

        self.tasks = [
            asyncio.create_task(self._run_exchange_streams(exchange_config, subs))
            for exchange_config, subs in groups.items()
        ]

        logger.info(f"Запущено {len(self.tasks)} клиентских задач")

        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(*self.tasks)

        logger.info("WebSocketStreamManager завершён.")

    def _handle_signal(self) -> None:
        logger.info("Получен сигнал завершения, останавливаем стримы...")
        self.shutdown_event.set()
        for task in self.tasks:
            task.cancel()

    async def _run_exchange_streams(
        self,
        exchange_config: ExchangeConfig,
        subs: list[SubscriptionConfig],
    ) -> None:
        """Открывает exchange через контекстный менеджер и запускает все его стримы."""
        exchange = self._build_exchange(exchange_config)
        if not exchange:
            return

        async with exchange:
            stream_tasks = [
                asyncio.create_task(
                    OHLCVStream(
                        exchange=exchange,
                        symbol=sub.symbol,
                        timeframe=sub.timeframe,
                        on_candle=self.on_candle,
                        shutdown_event=self.shutdown_event,
                        source_id=sub.source_id,
                    ).run(),
                    name=f"ohlcv:{sub.symbol}:{sub.timeframe}",
                )
                for sub in subs
            ]
            try:
                await asyncio.gather(*stream_tasks)
            except asyncio.CancelledError:
                for t in stream_tasks:
                    t.cancel()
                raise

    # Маппинг имён аргументов домена → ключи ccxt
    _CCXT_PARAM_MAP: dict[str, str] = {
        "api_key": "apiKey",
        "api_secret": "secret",  # nosec B105
        "password": "password",  # nosec B105
        "wallet": "walletAddress",
        "private_key": "privateKey",
    }

    def _build_exchange(self, config: ExchangeConfig) -> Any:
        """Создаёт ccxt.pro exchange по ExchangeConfig."""
        ccxt_id = CLASS_NAME_TO_CCXT_PRO.get(config.class_name)

        if not ccxt_id:
            logger.error(f"Нет маппинга ccxt.pro для {config.class_name}")
            return None

        exchange_class = getattr(ccxtpro, ccxt_id, None)
        if not exchange_class:
            logger.error(f"ccxt.pro не поддерживает {ccxt_id}")
            return None

        exchange_config: dict[str, Any] = {
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        }

        demo = False
        for key, value in config.arguments.items():
            if key == "demo":
                demo = value
            elif key in self._CCXT_PARAM_MAP:
                exchange_config[self._CCXT_PARAM_MAP[key]] = value

        if config.proxy_url:
            exchange_config["proxies"] = {
                "http": config.proxy_url,
                "https": config.proxy_url,
            }

        exchange = exchange_class(exchange_config)

        if demo:
            try:
                exchange.enable_demo_trading(True)
            except Exception:
                logger.warning(f"Demo trading не поддерживается для {ccxt_id}")

        return exchange
