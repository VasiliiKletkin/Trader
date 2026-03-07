import asyncio
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
os.environ.setdefault("LOG_LEVEL", "WARNING")
django.setup()

from decimal import Decimal  # noqa: E402

from exchange_clients.domain.exchange_clients import ByBitExchangeClient  # noqa: E402
from exchanges.domain import (  # noqa: E402
    BybitExchange,
    MarketType,
    Timeframe,
    TradingPair,
)

# --- Скрипт 3: Spot + Futures одновременно (через ByBitExchangeClient) ---


async def watch(client, trading_pair, timeframe, label):
    async with client:
        while True:
            candles = await client.watch_ohlcv(trading_pair, timeframe)
            for c in candles:
                print(
                    f"[{label}] ts={c.dt_unix} O={c.open} H={c.high} "
                    f"L={c.low} C={c.close} V={c.volume}"
                )


async def main_spot_futures():
    client = ByBitExchangeClient(  # nosec B106
        exchange=BybitExchange(name="ByBit"),
        api_key="GqezJS4VMcdYYKPDMs",
        api_secret="SEyRiSft5zc6pICTGx4tgu8K3XxHoMl7ESpP",
        demo=True,
    )

    futures_pair = TradingPair(
        name="BTC/USDT",
        symbol="BTC/USDT:USDT",
        type=MarketType.FUTURES,
        min_amount=Decimal("0.001"),
        max_amount=Decimal("1000000"),
        fee_percent=Decimal("0.1"),
    )
    spot_pair = TradingPair(
        name="BTC/USDT",
        symbol="BTC/USDT",
        type=MarketType.SPOT,
        min_amount=Decimal("0.001"),
        max_amount=Decimal("1000000"),
        fee_percent=Decimal("0.1"),
    )

    print("Подключаюсь к ByBit Demo WebSocket (Spot + Futures)...")
    await asyncio.gather(
        watch(client, futures_pair, Timeframe.ONE_MINUTE, "FUTU"),
        watch(client, spot_pair, Timeframe.ONE_MINUTE, "SPOT"),
    )


asyncio.run(main_spot_futures())
