from decimal import Decimal

import ccxt.async_support as ccxt

from ..schemas import Exchange, MarketType, TradingPair, parse_decimal


class BinanceExchange(Exchange):
    """BinanceExchange."""

    client_class_name: str = "BinanceExchangeClient"

    async def load_markets(self) -> list[TradingPair]:
        client = ccxt.binance(
            {"enableRateLimit": True, "options": {"defaultType": "future"}}
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

            limits = market.get("limits", {}).get("amount", {})
            taker = parse_decimal(market.get("taker"), Decimal("0"))
            maker = parse_decimal(market.get("maker"), Decimal("0"))
            result.append(
                TradingPair(
                    name=f"{base}/{quote}",
                    symbol=symbol,
                    type=market_type,
                    min_amount=parse_decimal(limits.get("min"), Decimal("0.001")),
                    max_amount=parse_decimal(limits.get("max"), Decimal("1000000")),
                    fee_percent=taker * 100,
                    taker_fee=taker,
                    maker_fee=maker,
                )
            )
        return result
