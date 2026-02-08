from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class Candle(BaseModel):
    dt_unix: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    @property
    def timestamp(self) -> datetime:
        return datetime.fromtimestamp(self.dt_unix / 1000, tz=UTC)

    @property
    def type(self) -> Literal["up", "down"]:
        return "up" if self.close >= self.open else "down"


class ExchangeCandle(Candle):
    id: int


class TradingPair(BaseModel):
    name: str
    symbol: str
    min_amount: Decimal
    max_amount: Decimal
    fee_percent: Decimal


class Timeframe(StrEnum):
    ONE_MINUTE = "1m"
    FIVE_MINUTES = "5m"
    FIFTEEN_MINUTES = "15m"
    ONE_HOUR = "1h"
    FOUR_HOURS = "4h"
    ONE_DAY = "1d"
    ONE_WEEK = "1w"
