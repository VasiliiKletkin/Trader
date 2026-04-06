import traceback
from collections.abc import AsyncIterator
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

    async def _fetch_candles_batch(
        self,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[Candle]:
        """Один запрос к API биржи."""
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
                    message=getattr(e, "error_message", None) or str(e),
                    type=getattr(e, "error_type", None) or type(e).__name__,
                    traceback=getattr(e, "error_traceback", None)
                    or traceback.format_exc(),
                )
            )
            return []

    async def fetch_candles(
        self,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[Candle]:
        """Скачивает все свечи, собирая батчи из fetch_candles_iter."""
        seen: dict[datetime, Candle] = {}
        async for batch in self.fetch_candles_iter(since=since, limit=limit):
            for c in batch:
                seen[c.timestamp] = c
        return list(seen.values())

    async def fetch_candles_iter(
        self,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[list[Candle]]:
        """Итератор: отдаёт свечи батчами, последовательно."""
        now = datetime.now(tz=UTC)
        if since and since > now:
            raise ValueError("Since не может быть в будущем.")

        max_per_req = self.exchange_client.exchange.max_candles_per_request
        step_delta = self.timeframe.timedelta() * max_per_req

        total_steps = 1
        if since:
            total_steps = ((now - since) // step_delta) + 1
        if limit:
            total_steps = min(total_steps, (limit // max_per_req) + 1)

        fetched = 0
        for i in range(total_steps):
            batch_limit = max_per_req
            if limit:
                batch_limit = min(max_per_req, limit - fetched)
                if batch_limit <= 0:
                    break

            candles = await self._fetch_candles_batch(
                since=since + i * step_delta if since else None,
                limit=batch_limit,
            )
            if not candles:
                break

            yield candles
            fetched += len(candles)
