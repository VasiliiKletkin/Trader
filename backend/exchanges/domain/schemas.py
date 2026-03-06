from datetime import UTC, datetime, timedelta
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


class MarketType(StrEnum):
    FUTURES = "futures"
    SPOT = "spot"


class TradingPair(BaseModel):
    name: str
    symbol: str
    type: MarketType
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

    def timedelta(self) -> timedelta:
        return {
            self.ONE_MINUTE: timedelta(minutes=1),
            self.FIVE_MINUTES: timedelta(minutes=5),
            self.FIFTEEN_MINUTES: timedelta(minutes=15),
            self.ONE_HOUR: timedelta(hours=1),
            self.FOUR_HOURS: timedelta(hours=4),
            self.ONE_DAY: timedelta(days=1),
            self.ONE_WEEK: timedelta(weeks=1),
        }[self]
