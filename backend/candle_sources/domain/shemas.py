from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from exchanges.domain import ExchangeCandle


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


class ProviderCandle(Candle):
    first_candle: ExchangeCandle
    second_candle: ExchangeCandle | None = None
