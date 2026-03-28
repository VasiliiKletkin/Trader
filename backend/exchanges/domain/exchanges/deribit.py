import ccxt.async_support as ccxt

from ..schemas import Exchange, MarketType, TradingPair, safe_decimal


class DeribitExchange(Exchange):
    """DeribitExchange."""

    client_class_name: str = "DeribitExchangeClient"

    async def load_markets(self) -> list[TradingPair]:
        client = ccxt.deribit({"enableRateLimit": True})
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

            kwargs: dict = {
                "name": f"{base}/{quote}",
                "symbol": symbol,
                "type": market_type,
                "min_amount": safe_decimal(amount_limits.get("min")),
                "max_amount": safe_decimal(amount_limits.get("max")),
            }
            taker_fee = safe_decimal(market.get("taker"))
            if taker_fee is not None:
                kwargs["taker_fee"] = taker_fee
            maker_fee = safe_decimal(market.get("maker"))
            if maker_fee is not None:
                kwargs["maker_fee"] = maker_fee
            max_leverage = safe_decimal(leverage_limits.get("max"))
            if max_leverage is not None:
                kwargs["max_leverage"] = max_leverage

            result.append(TradingPair(**kwargs))
        return result
