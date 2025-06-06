from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List

from exchanges.domain.exchanges.schemas import Candle

from .base import AbstractExchange
from ccxt.base.types import OrderSide
import ccxt.async_support as ccxt
from loguru import logger


class ByBitExchange(AbstractExchange):
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        demo: bool = True,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.exchange = ccxt.bybit(
            {
                "apiKey": self.api_key,
                "secret": self.api_secret,
                "enableRateLimit": True,
                "options": {
                    "defaultType": "future",
                },
            }
        )
        if demo:
            self.exchange.enable_demo_trading(True)
        logger.info(
            f"ByBitExchange инициализирован. Demo режим: {demo}",
        )

    async def connect(self) -> None:
        await self.exchange.load_markets()
        logger.info("Соединение с ByBit установлено.")

    async def close(self) -> None:
        await self.exchange.close()
        logger.info("Соединения с ByBit закрыты.")

    async def get_market_candles(
        self,
        symbol: str,
        timeframe: str = "1m",
        since: datetime | None = None,
        limit: int = None,
    ) -> List[Candle]:
        if isinstance(since, datetime):
            since = int(since.timestamp() * 1000)

        raw_ohlcv = await self.exchange.fetch_ohlcv(
            symbol,
            timeframe,
            limit=limit,
            since=since,
        )
        return [
            Candle(
                dt_unix=item[0],
                open=item[1],
                high=item[2],
                low=item[3],
                close=item[4],
                volume=item[5],
            )
            for item in raw_ohlcv
        ]

    async def get_balance(self) -> Dict[str, float]:
        balance = await self.exchange.fetch_balance()
        return {k: v["free"] for k, v in balance["total"].items()}

    async def get_price(self, symbol: str) -> float:
        ticker = await self.exchange.fetch_ticker(symbol)
        return ticker["last"]

    async def create_market_order(
        self, symbol: str, side: OrderSide, amount: float, price: float
    ) -> Dict[str, Any]:
        return await self.exchange.create_market_order(symbol, side, amount, price)

    async def get_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        return await self.exchange.fetch_open_orders(symbol)

    async def cancel_all_orders(self, symbol: str) -> None:
        await self.exchange.cancel_all_orders(symbol)
