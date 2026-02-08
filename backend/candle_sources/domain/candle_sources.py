from datetime import datetime

from pydantic import BaseModel

from exchange_clients.domain import AbstractExchangeClient
from exchanges.domain import Candle, Timeframe, TradingPair


class CandleSourceError(BaseModel):
    """Ошибка при получении свечей."""

    message: str
    type: str
    traceback: str | None = None


class CandleSource:
    def __init__(
        self,
        exchange_client: AbstractExchangeClient,
        trading_pair: TradingPair,
        timeframe: Timeframe,
    ):
        self.exchange_client = exchange_client
        self.trading_pair = trading_pair
        self.timeframe = timeframe
        self.errors: list[CandleSourceError] = []

    async def __aenter__(self) -> "CandleSource":
        await self.exchange_client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.exchange_client.__aexit__(exc_type, exc, tb)

    async def fetch_candles(
        self,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[Candle]:
        return await self.exchange_client.fetch_candles(
            trading_pair=self.trading_pair,
            timeframe=self.timeframe,
            since=since,
            limit=limit,
        )
