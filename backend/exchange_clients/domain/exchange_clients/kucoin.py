from datetime import datetime
from decimal import Decimal
from typing import Any

import ccxt.async_support as ccxt
from django.utils import timezone
from loguru import logger

from exchanges.domain import Candle, KuCoinExchange, Timeframe, TradingPair

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
class KuCoinExchangeClient(AbstractExchangeClient):
    """Клиент для KuCoin Futures."""

    def __init__(
        self,
        exchange: KuCoinExchange,
        api_key: str = "API_KEY",
        api_secret: str = "API_SECRET",
        password: str = "PASSWORD",
        demo: bool = True,
        proxy: ExchangeClientProxy | None = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.password = password
        self.demo = demo
        self.proxy = proxy
        self.exchange = exchange
        self.client = ccxt.kucoinfutures(
            {
                "apiKey": self.api_key,
                "secret": self.api_secret,
                "password": self.password,
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

        order: dict = await self.client.create_market_order(
            symbol=trading_pair.symbol,
            side=side,
            amount=amount,
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

    async def watch_ohlcv(
        self,
        trading_pair: TradingPair,
        timeframe: Timeframe,
    ) -> list[Candle]:
        raw_ohlcv = await self.client.watch_ohlcv(trading_pair.symbol, timeframe.value)
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

    async def watch_ohlcv_for_symbols(
        self,
        subscriptions: list[tuple[TradingPair, Timeframe]],
    ) -> dict[TradingPair, dict[Timeframe, list[Candle]]]:
        symbol_to_tp = {tp.symbol: tp for tp, _ in subscriptions}
        value_to_tf = {tf.value: tf for _, tf in subscriptions}
        raw = await self.client.watch_ohlcv_for_symbols(
            [[tp.symbol, tf.value] for tp, tf in subscriptions]
        )
        return {
            symbol_to_tp[symbol]: {
                value_to_tf[tf_value]: [
                    Candle(
                        dt_unix=item[0],
                        open=item[1],
                        high=item[2],
                        low=item[3],
                        close=item[4],
                        volume=item[5],
                    )
                    for item in ohlcvs
                ]
                for tf_value, ohlcvs in timeframes.items()
            }
            for symbol, timeframes in raw.items()
        }

    async def __aenter__(self) -> "KuCoinExchangeClient":
        await self.client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.client is not None:
            await self.client.__aexit__(exc_type, exc, tb)


if __name__ == "__main__":
    import asyncio

    from exchanges.domain.schemas import MarketType

    async def main():
        exchange = KuCoinExchange(name="KuCoin")
        client = KuCoinExchangeClient(exchange=exchange, demo=False)
        tp_btc = TradingPair(
            name="BTC/USDT",
            symbol="BTC/USDT:USDT",
            type=MarketType.FUTURES,
            taker_fee=Decimal("0.0004"),
        )
        tp_eth = TradingPair(
            name="ETH/USDT",
            symbol="ETH/USDT:USDT",
            type=MarketType.FUTURES,
            taker_fee=Decimal("0.0004"),
        )
        tf = Timeframe.ONE_MINUTE

        async with client:
            print("=== fetch_candles ===")
            candles = await client.fetch_candles(tp_btc, tf, limit=3)
            for c in candles:
                print(f"  {c.timestamp} O={c.open} H={c.high} L={c.low} C={c.close}")

            print("\n=== watch_ohlcv ===")
            for _ in range(3):
                ohlcv = await client.watch_ohlcv(tp_btc, tf)
                for c in ohlcv:
                    print(f"  {c.timestamp} C={c.close} V={c.volume}")

            print("\n=== watch_ohlcv_for_symbols ===")
            for _ in range(3):
                result = await client.watch_ohlcv_for_symbols(
                    [(tp_btc, tf), (tp_eth, tf)]
                )
                for pair, timeframes in result.items():
                    for timeframe, candles in timeframes.items():
                        for c in candles:
                            print(
                                f"  {pair.symbol} {timeframe.value} {c.timestamp} C={c.close}"
                            )

    asyncio.run(main())
