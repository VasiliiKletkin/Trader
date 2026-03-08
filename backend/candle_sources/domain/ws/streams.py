import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from loguru import logger

from exchange_clients.domain import AbstractExchangeClient
from exchanges.domain import Timeframe, TradingPair


class OHLCVStream:
    """Стрим OHLCV свечей через ccxt.pro watch_ohlcv."""

    MAX_BACKOFF = 60

    def __init__(
        self,
        exchange_client: AbstractExchangeClient,
        trading_pair: TradingPair,
        timeframe: Timeframe,
        on_candle: Callable[..., Coroutine],
        shutdown_event: asyncio.Event,
        source_id: int,
    ):
        self.exchange_client = exchange_client
        self.trading_pair = trading_pair
        self.timeframe = timeframe
        self.on_candle = on_candle
        self.shutdown_event = shutdown_event
        self.source_id = source_id

    async def run(self) -> None:
        backoff = 1
        symbol = self.trading_pair.symbol
        timeframe_value = self.timeframe.value
        while not self.shutdown_event.is_set():
            try:
                ohlcvs = await self.exchange_client.client.watch_ohlcv(
                    symbol, timeframe_value
                )
                backoff = 1
                for ohlcv in ohlcvs:
                    await self.on_candle(
                        source_id=self.source_id,
                        exchange=self.exchange_client.exchange,
                        trading_pair=self.trading_pair,
                        timeframe=self.timeframe,
                        ohlcv=ohlcv,
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    f"OHLCVStream ошибка [{symbol} {timeframe_value}]: "
                    f"{type(e).__name__}: {e}"
                )
                await asyncio.sleep(min(backoff, self.MAX_BACKOFF))
                backoff = min(backoff * 2, self.MAX_BACKOFF)


class OrderBookStream:
    """Стрим стакана через ccxt.pro watch_order_book."""

    MAX_BACKOFF = 60

    def __init__(
        self,
        exchange: Any,
        symbol: str,
        on_orderbook: Callable[..., Coroutine],
        shutdown_event: asyncio.Event,
        source_id: int,
        limit: int = 20,
    ):
        self.exchange = exchange
        self.symbol = symbol
        self.on_orderbook = on_orderbook
        self.shutdown_event = shutdown_event
        self.source_id = source_id
        self.limit = limit

    async def run(self) -> None:
        backoff = 1
        while not self.shutdown_event.is_set():
            try:
                orderbook = await self.exchange.watch_order_book(
                    self.symbol, self.limit
                )
                backoff = 1
                await self.on_orderbook(
                    source_id=self.source_id,
                    orderbook=orderbook,
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    f"OrderBookStream ошибка [{self.symbol}]: {type(e).__name__}: {e}"
                )
                await asyncio.sleep(min(backoff, self.MAX_BACKOFF))
                backoff = min(backoff * 2, self.MAX_BACKOFF)
