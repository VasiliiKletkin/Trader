import ccxt.async_support as ccxt

from ..schemas import Exchange, ExchangeRegistry, MarketType, TradingPair, safe_decimal


@ExchangeRegistry.register
class BitgetExchange(Exchange):
    """BitgetExchange."""

    client_class_name: str = "BitgetExchangeClient"

    async def fetch_trading_pairs(self, market_type: MarketType) -> list[TradingPair]:
        ccxt_type = {"futures": "swap", "spot": "spot"}.get(market_type, "swap")
        client = ccxt.bitget(
            {
                "enableRateLimit": True,
                "options": {"defaultType": ccxt_type},
            }
        )
        try:
            raw_markets = await client.load_markets()
        finally:
            await client.close()

        result = []
        for symbol, market in raw_markets.items():
            if market.get("expiry"):
                continue
            if market.get("type") != ccxt_type:
                continue
            base = market.get("base", "")
            quote = market.get("quote", "")
            if not base or not quote:
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
                "base_currency": base,
                "quote_currency": quote,
                "market_type": market_type,
                "min_amount": safe_decimal(amount_limits.get("min")),
                "max_amount": safe_decimal(amount_limits.get("max")),
                "min_cost": safe_decimal(cost_limits.get("min")),
                "max_cost": safe_decimal(cost_limits.get("max")),
                "min_price": safe_decimal(price_limits.get("min")),
                "max_price": safe_decimal(price_limits.get("max")),
                "price_precision": safe_decimal(precision.get("price")),
                "amount_precision": safe_decimal(precision.get("amount")),
                "is_active": bool(market.get("active", True)),
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
            kwargs["settle_currency"] = market.get("settle") or ""
            linear = market.get("linear")
            if linear is not None:
                kwargs["is_linear"] = linear
            contract_size = safe_decimal(market.get("contractSize"))
            if contract_size is not None:
                kwargs["contract_size"] = contract_size

            result.append(TradingPair(**kwargs))
        return result
