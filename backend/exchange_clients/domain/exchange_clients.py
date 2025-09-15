from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

import ccxt.async_support as ccxt  # Асинхронная версия ccxt
from ccxt.base.types import OrderSide
from django.utils import timezone
from exchanges.domain.schemas import Candle
from loguru import logger

from .base import AbstractExchangeClient
from .schemas import ExchangeClientOrder, OrderStatus, TradingPair


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

    async def close(self):
        await self.exchange.close()

    async def get_candles(
        self,
        trading_pair: str,
        timeframe: str = "1m",
        since: datetime | None = None,
        limit: int = None,
        params: dict = {},
    ) -> List[Candle]:
        if isinstance(since, datetime):
            since = int(since.timestamp() * 1000)

        raw_ohlcv = await self.exchange.fetch_ohlcv(
            trading_pair, timeframe, limit=limit, since=since, params=params
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

    async def get_balances(self, params: Optional[dict] = None) -> Dict[str, Decimal]:
        if params is None:
            params = {}
        balance_dict = await self.exchange.fetch_balance(params=params)
        return {k: v for k, v in balance_dict["free"].items()}

    async def get_orders(
        self,
        trading_pair: str,
        since: int | None = None,
        limit: int | None = None,
        params: Optional[dict] = None,
    ) -> List[ExchangeClientOrder]:
        if params is None:
            params = {}
        try:
            orders = await self.exchange.fetch_orders(
                symbol=trading_pair,
                since=since,
                limit=limit,
                params=params,
            )
        except Exception as e:
            logger.error(f"Ошибка при получении ордеров: {e}")
            return []

        result: List[ExchangeClientOrder] = []
        for order in orders:
            try:
                order_dto = ExchangeClientOrder(
                    timestamp=order["timestamp"],
                    side=order["side"],
                    price=order["price"],
                    amount=order["amount"],
                    status=order["status"],
                )
                result.append(order_dto)
            except Exception as e:
                logger.warning(f"Ошибка при валидации ордера {order}: {e}")
        return result

    async def create_market_order(
        self,
        trading_pair: TradingPair,
        side: OrderSide,
        amount: Decimal,
        price: Optional[Decimal] = None,
        params: Optional[dict] = None,
    ) -> Dict[str, Any]:
        if params is None:
            params = {}

        order_dict_id: Dict = await self.exchange.create_market_order(
            symbol=trading_pair.symbol,
            side=side,
            amount=amount,
            price=price,
            params=params,
        )

        order_id = order_dict_id.get("id")
        order_dict = await self.exchange.fetch_open_order(order_id, trading_pair.symbol)

        return ExchangeClientOrder(
            trading_pair=trading_pair,
            side=side,
            amount=Decimal(str(order_dict["amount"])),
            price=Decimal(str(order_dict["average"])),
            status=OrderStatus(order_dict["status"]),
            timestamp=timezone.make_aware(
                datetime.fromtimestamp(order_dict["timestamp"] / 1000)
            ),
            exchange_order_id=order_dict["id"],
            fee=Decimal(str(order_dict["fee"]["cost"])),
        )

    async def get_open_orders(
        self, trading_pair: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        return await self.exchange.fetch_open_orders(trading_pair)

    async def cancel_all_orders(self, trading_pair: str) -> None:
        await self.exchange.cancel_all_orders(trading_pair)
