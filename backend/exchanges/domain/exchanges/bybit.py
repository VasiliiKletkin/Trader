from datetime import datetime
from typing import Any, Dict, List, Optional

import ccxt
from ccxt.base.types import OrderSide
from exchanges.domain.schemas import CandleDTO, OrderDTO
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

    def get_candles(
        self,
        trading_pair: str,
        timeframe: str = "1m",
        since: datetime | None = None,
        limit: int = None,
        params: dict = {},
    ) -> List[CandleDTO]:
        if isinstance(since, datetime):
            since = int(since.timestamp() * 1000)

        raw_ohlcv = self.exchange.fetch_ohlcv(
            trading_pair, timeframe, limit=limit, since=since, params=params
        )
        return [
            CandleDTO(
                dt_unix=item[0],
                open=item[1],
                high=item[2],
                low=item[3],
                close=item[4],
                volume=item[5],
            )
            for item in raw_ohlcv
        ]

    def get_balances(self, params: Optional[dict] = None) -> Dict[str, float]:
        balance = self.exchange.fetch_balance(params=params)
        return {k: v["free"] for k, v in balance["total"].items()}

    def get_orders(
        self,
        trading_pair: str,
        since: int | None = None,
        limit: int | None = None,
        params: dict = None,
    ) -> List[OrderDTO]:
        try:
            orders = self.exchange.fetch_orders(
                symbol=trading_pair,
                since=since,
                limit=limit,
                params=params or {},
            )
        except Exception as e:
            logger.error(f"Ошибка при получении ордеров: {e}")
            return []

        result: List[OrderDTO] = []
        for order in orders:
            try:
                order_dto = OrderDTO(
                    timestamp=order["timestamp"],
                    side=order["side"],
                    price=float(order["price"]),
                    amount=float(order["amount"]),
                    status=order["status"],
                )
                result.append(order_dto)
            except Exception as e:
                logger.warning(f"Ошибка при валидации ордера {order}: {e}")
        return result

    def create_market_order(
        self,
        trading_pair: str,
        side: OrderSide,
        amount: float,
        price: Optional[float] = None,
        params: Optional[dict] = None,
    ) -> Dict[str, Any]:
        return self.exchange.create_market_order(
            symbol=trading_pair,
            side=side,
            amount=amount,
            price=price,
            params=params,
        )

    def get_open_orders(self, trading_pair: str) -> List[Dict[str, Any]]:
        return self.exchange.fetch_open_orders(trading_pair)

    def cancel_all_orders(self, trading_pair: str) -> None:
        self.exchange.cancel_all_orders(trading_pair)
