import asyncio
import traceback
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from typing import Any

from exchange_clients.domain import AbstractExchangeClient
from exchanges.domain import Candle, Timeframe, TradingPair


class BaseStream(ABC):
    """Базовый WebSocket-стрим с exponential backoff."""

    MAX_BACKOFF = 60

    def __init__(
        self,
        trading_pair: TradingPair,
        on_error: Callable[..., Coroutine],
    ):
        self.trading_pair = trading_pair
        self.on_error = on_error

    @property
    def key(self) -> tuple:
        return (
            type(self).__name__,
            self.trading_pair.symbol,
        )

    async def run(
        self,
        exchange_client: AbstractExchangeClient,
        shutdown_event: asyncio.Event,
    ) -> None:
        backoff = 1
        while not shutdown_event.is_set():
            try:
                await self._process(exchange_client)
                backoff = 1
            except asyncio.CancelledError:
                break
            except Exception as e:
                tb = traceback.format_exc()
                await self.on_error(e, tb)
                await asyncio.sleep(min(backoff, self.MAX_BACKOFF))
                backoff = min(backoff * 2, self.MAX_BACKOFF)

    @abstractmethod
    async def _process(self, exchange_client: AbstractExchangeClient) -> None: ...


class OHLCVStream(BaseStream):
    """Стрим OHLCV свечей через watch_ohlcv."""

    def __init__(
        self,
        *,
        timeframe: Timeframe,
        on_candle: Callable[..., Coroutine],
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self.timeframe = timeframe
        self.on_candle = on_candle

    @property
    def key(self) -> tuple:
        return (*super().key, self.timeframe.value)

    async def _process(self, exchange_client: AbstractExchangeClient) -> None:
        ohlcvs = await exchange_client.client.watch_ohlcv(
            self.trading_pair.symbol, self.timeframe.value
        )
        for ohlcv in ohlcvs:
            candle = Candle(
                dt_unix=ohlcv[0],
                open=ohlcv[1],
                high=ohlcv[2],
                low=ohlcv[3],
                close=ohlcv[4],
                volume=ohlcv[5],
            )
            await self.on_candle(
                exchange=exchange_client.exchange,
                trading_pair=self.trading_pair,
                timeframe=self.timeframe,
                candle=candle,
            )


class BalanceStream(BaseStream):
    """Стрим баланса через watch_balance."""

    def __init__(
        self,
        *,
        on_balance: Callable[..., Coroutine],
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self.on_balance = on_balance

    async def _process(self, exchange_client: AbstractExchangeClient) -> None:
        balance = await exchange_client.client.watch_balance()
        await self.on_balance(balance=balance)


class OrdersStream(BaseStream):
    """Стрим ордеров через watch_orders."""

    def __init__(
        self,
        *,
        on_orders: Callable[..., Coroutine],
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self.on_orders = on_orders

    async def _process(self, exchange_client: AbstractExchangeClient) -> None:
        orders = await exchange_client.client.watch_orders(self.trading_pair.symbol)
        await self.on_orders(orders=orders)


class OrderBookStream(BaseStream):
    """Стрим стакана через watch_order_book."""

    def __init__(
        self,
        *,
        limit: int = 20,
        on_orderbook: Callable[..., Coroutine],
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self.limit = limit
        self.on_orderbook = on_orderbook

    async def _process(self, exchange_client: AbstractExchangeClient) -> None:
        orderbook = await exchange_client.client.watch_order_book(
            self.trading_pair.symbol, self.limit
        )
        await self.on_orderbook(orderbook=orderbook)
