from datetime import datetime
from decimal import Decimal
from typing import Any

import ccxt.async_support as ccxt
from django.utils import timezone
from loguru import logger

from exchanges.domain import Candle, Timeframe, TradingPair

from ..base import AbstractExchangeClient
from ..proxies import ExchangeClientProxy
from ..schemas import (
    ExchangeClientBalance,
    ExchangeClientOrder,
    OrderSide,
    OrderStatus,
    OrderType,
)


class DeribitExchangeClient(AbstractExchangeClient):
    """Клиент для Deribit.

    Demo-режим (sandbox) отключён: демо-сервер Deribit не содержит
    исторических данных по свечам.
    """

    def __init__(
        self,
        api_key: str = "API_KEY",
        api_secret: str = "API_SECRET",
        proxy: ExchangeClientProxy | None = None,
        max_candles_per_request: int = 5000,
        timeout: int = 30000,
        rate_limit: int = 500,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.proxy = proxy
        self.max_candles_per_request = max_candles_per_request
        self.timeout = timeout
        self.rate_limit = rate_limit
        self.exchange = ccxt.deribit(
            {
                "apiKey": self.api_key,
                "secret": self.api_secret,
                "enableRateLimit": True,
            }
        )
        self.exchange.timeout = self.timeout
        self.exchange.rateLimit = self.rate_limit

    async def fetch_candles(
        self,
        trading_pair: TradingPair,
        timeframe: Timeframe = Timeframe.ONE_MINUTE,
        since: datetime | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[Candle]:
        if params is None:
            params = {}
        since_ms: int | None = (
            int(since.timestamp() * 1000) if isinstance(since, datetime) else None
        )
        raw_ohlcv = await self.exchange.fetch_ohlcv(
            trading_pair.symbol,
            timeframe.value,
            limit=limit,
            since=since_ms,
            params=params,
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

    async def get_balances(
        self, params: dict | None = None
    ) -> list[ExchangeClientBalance]:
        if params is None:
            params = {}
        balances_dict = await self.exchange.fetch_balance(params=params)
        return [
            ExchangeClientBalance(
                currency=currency,
                free=values["free"],
                total=values["total"],
                debt=values.get("debt", Decimal(0)),
                used=values["used"],
            )
            for currency, values in balances_dict.items()
            if isinstance(values, dict)
            and all(
                key in values and values[key] is not None
                for key in ("free", "total", "used")
            )
        ]

    async def get_orders(
        self,
        trading_pair: TradingPair | None = None,
        since: int | None = None,
        limit: int | None = None,
        params: dict[str, Any] | None = None,
    ) -> list[ExchangeClientOrder]:
        if trading_pair is None:
            return []
        if params is None:
            params = {}
        try:
            orders = await self.exchange.fetch_orders(
                symbol=trading_pair.symbol,
                since=since,
                limit=limit,
                params=params,
            )
        except Exception as e:
            logger.error(f"Ошибка при получении ордеров: {e}")
            return []

        result: list[ExchangeClientOrder] = []
        for order in orders:
            try:
                order_dto = ExchangeClientOrder(
                    trading_pair=trading_pair,
                    exchange_order_id=str(order.get("id", "")),
                    type=OrderType(order.get("type", "market")),
                    timestamp=timezone.make_aware(
                        datetime.fromtimestamp(order["timestamp"] / 1000)
                    ),
                    side=OrderSide(order["side"]),
                    price=Decimal(str(order.get("price", 0))),
                    amount=Decimal(str(order.get("amount", 0))),
                    status=OrderStatus(order["status"]),
                    fee=Decimal(str(order.get("fee", {}).get("cost", 0)))
                    if order.get("fee")
                    else Decimal(0),
                    cost=Decimal(str(order.get("cost", 0))),
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
        price: Decimal | None = None,
        params: dict | None = None,
    ) -> ExchangeClientOrder:
        if params is None:
            params = {}

        order_dict_id: dict = await self.exchange.create_market_order(
            symbol=trading_pair.symbol,
            side=side,
            amount=amount,
            params=params,
        )

        order_id = order_dict_id.get("id")
        order_dict = await self.exchange.fetch_order(order_id, trading_pair.symbol)

        return ExchangeClientOrder(
            trading_pair=trading_pair,
            side=side,
            type=OrderType.MARKET,
            amount=Decimal(str(order_dict["amount"])),
            price=Decimal(str(order_dict["average"])),
            status=OrderStatus(order_dict["status"]),
            timestamp=timezone.make_aware(
                datetime.fromtimestamp(order_dict["timestamp"] / 1000)
            ),
            cost=Decimal(str(order_dict["cost"])),
            exchange_order_id=order_dict["id"],
            fee=Decimal(str(order_dict["fee"]["cost"]))
            if order_dict.get("fee")
            else Decimal(0),
        )

    async def get_open_orders(
        self, trading_pair: TradingPair | None = None
    ) -> list[dict[str, Any]]:
        symbol = trading_pair.symbol if trading_pair else None
        return await self.exchange.fetch_open_orders(symbol)

    async def cancel_all_orders(self, trading_pair: TradingPair) -> None:
        await self.exchange.cancel_all_orders(trading_pair.symbol)
