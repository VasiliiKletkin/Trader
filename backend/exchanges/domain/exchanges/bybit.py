from datetime import datetime
from typing import Any, Dict, List

import ccxt
from ccxt.base.types import OrderSide
from exchanges.domain.schemas import Candle
from loguru import logger

from .base import AbstractExchangeClient


class ByBitExchangeClient(AbstractExchangeClient):
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
            f"ByBitExchangeClient инициализирован. Demo режим: {demo}",
        )

    def get_market_candles(
        self,
        trading_pair: str,
        timeframe: str = "1m",
        since: datetime | None = None,
        limit: int = None,
    ) -> List[Candle]:
        if isinstance(since, datetime):
            since = int(since.timestamp() * 1000)

        raw_ohlcv = self.exchange.fetch_ohlcv(
            trading_pair,
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

    def get_balance(self) -> Dict[str, float]:
        balance = self.exchange.fetch_balance()
        return {k: v["free"] for k, v in balance["total"].items()}

    def get_price(self, trading_pair: str) -> float:
        ticker = self.exchange.fetch_ticker(trading_pair)
        return ticker["last"]

    def create_market_order(
        self, trading_pair: str, side: OrderSide, amount: float, price: float
    ) -> Dict[str, Any]:
        return self.exchange.create_market_order(trading_pair, side, amount, price)

    def get_open_orders(self, trading_pair: str) -> List[Dict[str, Any]]:
        return self.exchange.fetch_open_orders(trading_pair)

    def cancel_all_orders(self, trading_pair: str) -> None:
        self.exchange.cancel_all_orders(trading_pair)
