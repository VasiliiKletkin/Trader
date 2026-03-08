import asyncio
import traceback
from datetime import UTC, datetime

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
        source_id: int | None = None,
    ):
        self.exchange_client = exchange_client
        self.trading_pair = trading_pair
        self.timeframe = timeframe
        self.source_id = source_id
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
        try:
            return await self.exchange_client.fetch_candles(
                trading_pair=self.trading_pair,
                timeframe=self.timeframe,
                since=since,
                limit=limit,
            )
        except Exception as e:
            self.errors.append(
                CandleSourceError(
                    message=str(e),
                    type=type(e).__name__,
                    traceback=traceback.format_exc(),
                )
            )
            return []

    async def fetch_candles_paginated(
        self,
        limit: int | None = None,
        since: datetime | None = None,
    ) -> list[Candle]:
        now = datetime.now(tz=UTC)
        if since and since > now:
            raise ValueError("Since не может быть в будущем.")

        max_candles_per_request = self.exchange_client.exchange.max_candles_per_request
        step_delta = self.timeframe.timedelta() * max_candles_per_request

        total_steps = 1
        if since:
            total_steps = ((now - since) // step_delta) + 1
        if limit:
            total_steps = min(total_steps, (limit // max_candles_per_request) + 1)

        tasks = [
            self.fetch_candles(
                limit=min(max_candles_per_request, limit - i * max_candles_per_request)
                if limit
                else max_candles_per_request,
                since=since + i * step_delta if since else None,
            )
            for i in range(total_steps)
        ]

        try:
            async with self.exchange_client:
                results: list[list[Candle]] = await asyncio.gather(*tasks)
        except Exception as e:
            self.errors.append(
                CandleSourceError(
                    message=str(e),
                    type=type(e).__name__,
                    traceback=traceback.format_exc(),
                )
            )
            return []

        candles: list[Candle] = []
        for result in results:
            candles.extend(result)

        # Дедупликация: шаги пагинации могут перекрываться по timestamp
        seen: dict[datetime, Candle] = {}
        for c in candles:
            seen[c.timestamp] = c
        return list(seen.values())
