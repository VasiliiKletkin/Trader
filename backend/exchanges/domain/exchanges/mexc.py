from decimal import Decimal

import ccxt.async_support as ccxt

from ..schemas import Exchange, MarketType, TradingPair, parse_decimal


class MEXCExchange(Exchange):
    """MEXCExchange."""

    client_class_name: str = "MEXCExchangeClient"

    async def load_markets(self) -> list[TradingPair]:
        client = ccxt.mexc(
            {"enableRateLimit": True, "options": {"defaultType": "swap"}}
        )
        try:
            raw_markets = await client.load_markets()
        finally:
            await client.close()

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
            leverage_limits = limits.get("leverage", {})
            taker = parse_decimal(market.get("taker"), Decimal("0"))
            maker = parse_decimal(market.get("maker"), Decimal("0"))
            max_leverage = leverage_limits.get("max")

            result.append(
                TradingPair(
                    name=f"{base}/{quote}",
                    symbol=symbol,
                    type=market_type,
                    min_amount=parse_decimal(
                        amount_limits.get("min"), Decimal("0.001")
                    ),
                    max_amount=parse_decimal(
                        amount_limits.get("max"), Decimal("1000000")
                    ),
                    fee_percent=taker * 100,
                    taker_fee=taker,
                    maker_fee=maker,
                    max_leverage=int(max_leverage) if max_leverage else 1,
                )
            )
        return result
