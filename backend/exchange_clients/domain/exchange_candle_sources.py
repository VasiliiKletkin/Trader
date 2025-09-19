from datetime import datetime
from typing import List, Optional
from exchange_clients.domain import AbstractExchangeClient
from exchanges.domain.schemas import Candle, Timeframe, TradingPair


class ExchangeClientCandleSource:
    def __init__(
        self,
        exchange_client: AbstractExchangeClient,
        trading_pair: TradingPair,
        timeframe: Timeframe,
    ):
        self.exchange_client = exchange_client
        self.trading_pair = trading_pair
        self.timeframe = timeframe

    async def __aenter__(self) -> "ExchangeClientCandleSource":
        await self.exchange_client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.exchange_client.__aexit__(exc_type, exc, tb)

    async def get_candles(
        self,
        since: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> List[Candle]:
        return await self.exchange_client.get_candles(
            trading_pair=self.trading_pair.symbol,
            timeframe=self.timeframe.value,
            since=since,
            limit=limit,
        )
