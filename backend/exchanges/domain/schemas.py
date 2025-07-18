from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from decimal import Decimal
from pydantic import BaseModel, Field


class CandleDTO(BaseModel):
    dt_unix: int = Field(description="Временная метка в формате UNIX (в мс)")
    open: Decimal = Field(description="Цена открытия свечи")
    high: Decimal = Field(description="Максимальная цена за период свечи")
    low: Decimal = Field(description="Минимальная цена за период свечи")
    close: Decimal = Field(description="Цена закрытия свечи")
    volume: Decimal = Field(description="Объём за период свечи")

    @property
    def timestamp(self) -> datetime:
        return datetime.fromtimestamp(self.dt_unix / 1000, tz=timezone.utc)

    @property
    def type(self) -> Literal["up", "down"]:
        return "up" if self.close >= self.open else "down"

    model_config = {
        "from_attributes": True,
        "populate_by_name": True,
        "extra": "forbid",
        "arbitrary_types_allowed": True,
    }


class OrderDTO(BaseModel):
    timestamp: datetime
    side: str = Field(..., description="buy or sell")
    price: Decimal
    amount: Decimal
    status: bool = Field(..., description="True if closed/filled, False otherwise")

    model_config = {
        "arbitrary_types_allowed": True,
    }


class TradingPairDTO(BaseModel):
    base: str = Field(..., description="Base currency of the trading pair")
    quote: str = Field(..., description="Quote currency of the trading pair")

    @property
    def symbol(self) -> str:
        return f"{self.base}/{self.quote}"


class TimeFrameDTO(str, Enum):
    ONE_MINUTE = "1m"
    FIVE_MINUTES = "5m"
    FIFTEEN_MINUTES = "15m"
    ONE_HOUR = "1h"
    FOUR_HOURS = "4h"
    ONE_DAY = "1d"
    ONE_WEEK = "1w"
