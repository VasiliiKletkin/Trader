import ccxt.async_support as ccxt

from ..schemas import Exchange, MarketType, TradingPair, safe_decimal


class WooFiProExchange(Exchange):
    """WooFiProExchange."""

    client_class_name: str = "WooFiProExchangeClient"

    async def load_markets(self) -> list[TradingPair]:
        client = ccxt.woofipro({"enableRateLimit": True})
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
                    min_amount=safe_decimal(amount_limits.get("min")),
                    max_amount=safe_decimal(amount_limits.get("max")),
                    taker_fee=safe_decimal(market.get("taker")),
                    maker_fee=safe_decimal(market.get("maker")),
                    max_leverage=safe_decimal(leverage_limits.get("max")),
                )
            )
        return result
