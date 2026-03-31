import json
from datetime import datetime
from decimal import Decimal
from typing import Any

import ccxt.async_support as ccxt
from django.utils import timezone
from loguru import logger
from websockets import connect as ws_connect

from exchanges.domain import Candle, HyperliquidExchange, Timeframe, TradingPair

from ..base import AbstractExchangeClient, ExchangeClientRegistry
from ..proxies import ExchangeClientProxy
from ..schemas import (
    ExchangeClientBalance,
    ExchangeClientOrder,
    OrderSide,
    OrderStatus,
    OrderType,
)


@ExchangeClientRegistry.register
class HyperliquidExchangeClient(AbstractExchangeClient):
    """Клиент для Hyperliquid."""

    def __init__(
        self,
        exchange: HyperliquidExchange,
        private_key: str = "PRIVATE_KEY",
        wallet_address: str = "WALLET_ADDRESS",
        demo: bool = True,
        proxy: ExchangeClientProxy | None = None,
    ):
        self.private_key = private_key
        self.wallet_address = wallet_address
        self.demo = demo
        self.proxy = proxy
        self.exchange = exchange
        self.client = ccxt.hyperliquid(
            {
                "privateKey": self.private_key,
                "walletAddress": self.wallet_address,
                "enableRateLimit": True,
            }
        )
        self.client.timeout = self.exchange.timeout
        self.client.rateLimit = self.exchange.rate_limit

        if self.demo:
            self.client.set_sandbox_mode(True)

    async def fetch_candles(
        self,
        trading_pair: TradingPair,
        timeframe: Timeframe,
        since: datetime | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[Candle]:
        if params is None:
            params = {}
        since_ms: int | None = (
            int(since.timestamp() * 1000) if isinstance(since, datetime) else None
        )
        raw_ohlcv = await self.client.fetch_ohlcv(
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
        balances_dict = await self.client.fetch_balance(params=params)
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
            orders = await self.client.fetch_orders(
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
        price: Decimal,
        params: dict | None = None,
    ) -> ExchangeClientOrder:
        if params is None:
            params = {}
        params.setdefault("user", self.wallet_address)

        order: dict = await self.client.create_market_order(
            symbol=trading_pair.symbol,
            side=side,
            amount=amount,
            price=price,
            params=params,
        )
        raw_amount = order.get("filled") or order.get("amount")
        order_amount: Decimal = Decimal(str(raw_amount)) if raw_amount else amount

        raw_price = order.get("average") or order.get("price")
        order_price: Decimal = Decimal(str(raw_price)) if raw_price else price

        raw_timestamp: int | None = order.get("timestamp")
        order_timestamp = (
            timezone.make_aware(datetime.fromtimestamp(raw_timestamp / 1000))
            if raw_timestamp
            else timezone.now()
        )

        raw_cost = order.get("cost")
        order_cost: Decimal = (
            Decimal(str(raw_cost)) if raw_cost else order_amount * order_price
        )

        raw_fee: dict | None = order.get("fee")
        order_fee: Decimal = (
            Decimal(str(raw_fee["cost"]))
            if raw_fee and raw_fee.get("cost")
            else order_amount * order_price * trading_pair.taker_fee
        )

        return ExchangeClientOrder(
            exchange_order_id=order["id"],
            trading_pair=trading_pair,
            side=side,
            status=OrderStatus.OPENED,
            type=OrderType.MARKET,
            timestamp=order_timestamp,
            amount=order_amount,
            price=order_price,
            cost=order_cost,
            fee=order_fee,
        )

    async def fetch_order(
        self,
        exchange_order_id: str,
        trading_pair: TradingPair,
    ) -> ExchangeClientOrder:
        """Получить ордер по ID с биржи."""
        order_dict: dict = await self.client.fetch_order(
            id=exchange_order_id,
            symbol=trading_pair.symbol,
        )
        raw_amount = order_dict.get("filled") or order_dict.get("amount")
        raw_price = order_dict.get("average") or order_dict.get("price")
        raw_timestamp: int | None = order_dict.get("timestamp")
        fee: dict | None = order_dict.get("fee")

        return ExchangeClientOrder(
            exchange_order_id=order_dict["id"],
            trading_pair=trading_pair,
            side=order_dict["side"],
            status=OrderStatus(order_dict.get("status") or "closed"),
            type=OrderType(order_dict.get("type") or "market"),
            timestamp=(
                timezone.make_aware(datetime.fromtimestamp(raw_timestamp / 1000))
                if raw_timestamp
                else timezone.now()
            ),
            amount=Decimal(str(raw_amount)) if raw_amount else Decimal(0),
            price=Decimal(str(raw_price)) if raw_price else Decimal(0),
            cost=Decimal(str(order_dict.get("cost") or 0)),
            fee=Decimal(str(fee["cost"])) if fee and fee.get("cost") else Decimal(0),
        )

    async def get_open_orders(
        self, trading_pair: TradingPair | None = None
    ) -> list[dict[str, Any]]:
        symbol = trading_pair.symbol if trading_pair else None
        return await self.client.fetch_open_orders(symbol)

    async def cancel_all_orders(self, trading_pair: TradingPair) -> None:
        await self.client.cancel_all_orders(trading_pair.symbol)

    WS_URL = "wss://api.hyperliquid.xyz/ws"
    WS_TESTNET_URL = "wss://api.hyperliquid-testnet.xyz/ws"

    _ws = None
    _ws_subscriptions: set[tuple[str, str]] = set()

    async def _ensure_ws(self) -> Any:
        """Подключается к WS если нет соединения."""
        if self._ws is None or self._ws.close_code is not None:
            url = self.WS_TESTNET_URL if self.demo else self.WS_URL
            self._ws = await ws_connect(url)
            self._ws_subscriptions = set()
        return self._ws

    async def _subscribe_candle(self, coin: str, interval: str) -> None:
        """Подписывается на канал candle если ещё не подписан."""
        key = (coin, interval)
        if key in self._ws_subscriptions:
            return
        ws = await self._ensure_ws()
        await ws.send(
            json.dumps(
                {
                    "method": "subscribe",
                    "subscription": {
                        "type": "candle",
                        "coin": coin,
                        "interval": interval,
                    },
                }
            )
        )
        self._ws_subscriptions.add(key)

    async def watch_ohlcv(
        self,
        trading_pair: TradingPair,
        timeframe: Timeframe,
    ) -> list[Candle]:
        """Получает свечу через нативный Hyperliquid WebSocket.

        Держит persistent-соединение. Каждый вызов блокирует
        до получения следующей свечи (аналогично ccxt watch_ohlcv).
        """
        coin = trading_pair.name.split("/")[0]
        await self._subscribe_candle(coin, timeframe.value)
        ws = await self._ensure_ws()

        async for raw_msg in ws:
            msg = json.loads(raw_msg)
            if msg.get("channel") != "candle":
                continue
            data = msg["data"]
            if data.get("s") != coin or data.get("i") != timeframe.value:
                continue
            return [
                Candle(
                    dt_unix=data["t"],
                    open=Decimal(data["o"]),
                    high=Decimal(data["h"]),
                    low=Decimal(data["l"]),
                    close=Decimal(data["c"]),
                    volume=Decimal(data["v"]),
                )
            ]
        return []

    async def watch_ohlcv_for_symbols(
        self,
        symbols_and_timeframes: list[list[str]],
    ) -> dict[str, dict[str, list[Candle]]]:
        """Подписка на несколько пар через нативный Hyperliquid WebSocket."""
        for symbol, interval in symbols_and_timeframes:
            coin = symbol.split("/")[0]
            await self._subscribe_candle(coin, interval)

        ws = await self._ensure_ws()

        async for raw_msg in ws:
            msg = json.loads(raw_msg)
            if msg.get("channel") != "candle":
                continue
            data = msg["data"]
            coin = data.get("s", "")
            interval = data.get("i", "")
            symbol = next(
                (
                    s
                    for s, i in symbols_and_timeframes
                    if s.split("/")[0] == coin and i == interval
                ),
                None,
            )
            if symbol is None:
                continue
            candle = Candle(
                dt_unix=data["t"],
                open=Decimal(data["o"]),
                high=Decimal(data["h"]),
                low=Decimal(data["l"]),
                close=Decimal(data["c"]),
                volume=Decimal(data["v"]),
            )
            return {symbol: {interval: [candle]}}
        return {}
