import ccxt.async_support as ccxt

from ..schemas import Exchange, MarketType, TradingPair


class PhemexExchange(Exchange):
    """PhemexExchange."""

    client_class_name: str = "PhemexExchangeClient"

    async def load_markets(self) -> list[TradingPair]:
        client = ccxt.phemex({"enableRateLimit": True})
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

            result.append(
                TradingPair(
                    name=f"{base}/{quote}",
                    symbol=symbol,
                    type=market_type,
                    min_amount=amount_limits.get("min"),
                    max_amount=amount_limits.get("max"),
                    taker_fee=market.get("taker"),
                    maker_fee=market.get("maker"),
                    max_leverage=leverage_limits.get("max"),
                )
            )
        return result
