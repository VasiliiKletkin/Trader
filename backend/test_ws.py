import asyncio
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
os.environ.setdefault("LOG_LEVEL", "WARNING")
django.setup()

from decimal import Decimal  # noqa: E402

from exchange_clients.domain.exchange_clients import (  # noqa: E402
    HyperliquidExchangeClient,
)
from exchanges.domain import (  # noqa: E402
    HyperliquidExchange,
    MarketType,
    Timeframe,
    TradingPair,
)


async def watch(client, trading_pair, timeframe, label):
    async with client:
        while True:
            candles = await client.watch_ohlcv(trading_pair, timeframe)
            for c in candles:
                print(
                    f"[{label}] ts={c.dt_unix} O={c.open} H={c.high} "
                    f"L={c.low} C={c.close} V={c.volume}"
                )


async def main():
    client = HyperliquidExchangeClient(  # nosec B106
        exchange=HyperliquidExchange(name="Hyperliquid"),
        private_key="PRIVATE_KEY",
        wallet_address="WALLET_ADDRESS",
        demo=True,
    )

    futures_pair = TradingPair(
        name="BTC/USDC",
        symbol="BTC/USDC:USDC",
        type=MarketType.FUTURES,
        min_amount=Decimal("0.001"),
        max_amount=Decimal("1000000"),
        fee_percent=Decimal("0.1"),
    )

    print("Подключаюсь к Hyperliquid Demo WebSocket...")
    await watch(client, futures_pair, Timeframe.ONE_MINUTE, "FUTU")


asyncio.run(main())
