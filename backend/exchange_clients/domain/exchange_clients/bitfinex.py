from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import ccxt.pro as ccxt
from loguru import logger

from exchanges.domain import BitfinexExchange, Candle, Timeframe, TradingPair
from exchanges.domain.schemas import MarketType, safe_decimal

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
class BitfinexExchangeClient(AbstractExchangeClient):
    """Клиент для Bitfinex."""

    def __init__(
        self,
        exchange: BitfinexExchange,
        api_key: str = "API_KEY",
        api_secret: str = "API_SECRET",
        demo: bool = False,
        proxy: ExchangeClientProxy | None = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.demo = demo
        self.proxy = proxy
        self.exchange = exchange
        self.client = ccxt.bitfinex(
            {
                "apiKey": self.api_key,
                "secret": self.api_secret,
                "enableRateLimit": True,
                "timeout": self.exchange.timeout,
                "rateLimit": self.exchange.rate_limit,
            }
        )

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
                    timestamp=datetime.fromtimestamp(order["timestamp"] / 1000, tz=UTC),
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
            datetime.fromtimestamp(raw_timestamp / 1000, tz=UTC)
            if raw_timestamp
            else datetime.now(UTC)
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
                datetime.fromtimestamp(raw_timestamp / 1000, tz=UTC)
                if raw_timestamp
                else datetime.now(UTC)
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

    async def cancel_all_orders(self, trading_pair: TradingPair | None = None) -> None:
        await self.client.cancel_all_orders(trading_pair.symbol)

    async def watch_balance(self) -> list[ExchangeClientBalance]:
        raw: dict = await self.client.watch_balance()
        return [
            ExchangeClientBalance(
                currency=currency,
                free=values["free"],
                total=values["total"],
                used=values["used"],
                debt=values.get("debt", Decimal(0)),
            )
            for currency, values in raw.items()
            if isinstance(values, dict)
            and all(
                key in values and values[key] is not None
                for key in ("free", "total", "used")
            )
        ]

    async def watch_orders(
        self,
        trading_pair: TradingPair,
    ) -> list[ExchangeClientOrder]:
        raw: list[dict] = await self.client.watch_orders(trading_pair.symbol)
        result: list[ExchangeClientOrder] = []
        for order in raw:
            try:
                raw_timestamp: int | None = order.get("timestamp")
                result.append(
                    ExchangeClientOrder(
                        trading_pair=trading_pair,
                        exchange_order_id=str(order.get("id", "")),
                        type=OrderType(order.get("type", "market")),
                        timestamp=(
                            datetime.fromtimestamp(
                                raw_timestamp / 1000,
                                tz=UTC,
                            )
                            if raw_timestamp
                            else datetime.now(UTC)
                        ),
                        side=OrderSide(order["side"]),
                        price=Decimal(str(order.get("price", 0))),
                        amount=Decimal(str(order.get("amount", 0))),
                        status=OrderStatus(order["status"]),
                        fee=(
                            Decimal(str(order.get("fee", {}).get("cost", 0)))
                            if order.get("fee")
                            else Decimal(0)
                        ),
                        cost=Decimal(str(order.get("cost", 0))),
                    ),
                )
            except Exception as e:
                logger.warning(f"Ошибка при валидации ордера {order}: {e}")
        return result

    async def watch_order_book(
        self,
        trading_pair: TradingPair,
        limit: int = 20,
    ) -> dict:
        return await self.client.watch_order_book(
            trading_pair.symbol,
            limit,
        )

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

    async def load_trading_pairs(self) -> list[TradingPair]:
        """Загружает торговые пары с биржи через ccxt load_markets."""
        raw_markets = await self.client.load_markets()
        result = []
        for symbol, market in raw_markets.items():
            if not market.get("active", True):
                continue
            base = market.get("base", "")
            quote = market.get("quote", "")
            if not base or not quote:
                continue

            if market.get("swap") or market.get("future"):
                market_type = MarketType.FUTURES
            elif market.get("spot"):
                market_type = MarketType.SPOT
            else:
                continue

            limits = market.get("limits", {})
            amount_limits = limits.get("amount", {})
            cost_limits = limits.get("cost", {})
            price_limits = limits.get("price", {})
            leverage_limits = limits.get("leverage", {})
            precision = market.get("precision", {})

            kwargs: dict = {
                "name": f"{base}/{quote}",
                "symbol": symbol,
                "type": market_type,
                "min_amount": safe_decimal(amount_limits.get("min")),
                "max_amount": safe_decimal(amount_limits.get("max")),
                "min_cost": safe_decimal(cost_limits.get("min")),
                "max_cost": safe_decimal(cost_limits.get("max")),
                "min_price": safe_decimal(price_limits.get("min")),
                "max_price": safe_decimal(price_limits.get("max")),
                "price_precision": safe_decimal(precision.get("price")),
                "amount_precision": safe_decimal(precision.get("amount")),
                "is_active": market.get("active", True),
            }
            taker_fee = safe_decimal(market.get("taker"))
            if taker_fee is not None:
                kwargs["taker_fee"] = taker_fee
            maker_fee = safe_decimal(market.get("maker"))
            if maker_fee is not None:
                kwargs["maker_fee"] = maker_fee
            min_leverage = safe_decimal(leverage_limits.get("min"))
            if min_leverage is not None:
                kwargs["min_leverage"] = min_leverage
            max_leverage = safe_decimal(leverage_limits.get("max"))
            if max_leverage is not None:
                kwargs["max_leverage"] = max_leverage

            result.append(TradingPair(**kwargs))
        return result

    async def __aenter__(self) -> "BitfinexExchangeClient":
        await self.client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.client is not None:
            await self.client.__aexit__(exc_type, exc, tb)


if __name__ == "__main__":
    import asyncio

    from exchanges.domain.schemas import MarketType

    async def main():
        exchange = BitfinexExchange(name="Bitfinex")
        client = BitfinexExchangeClient(exchange=exchange, demo=False)
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
