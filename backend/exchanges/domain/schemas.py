from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class CandleDTO(BaseModel):
    dt_unix: int = Field(description="Временная метка в формате UNIX (в мс)")
    open: float = Field(description="Цена открытия свечи")
    high: float = Field(description="Максимальная цена за период свечи")
    low: float = Field(description="Минимальная цена за период свечи")
    close: float = Field(description="Цена закрытия свечи")
    volume: float = Field(description="Объём за период свечи")

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
    }


class OrderDTO(BaseModel):
    timestamp: datetime
    side: str = Field(..., description="buy or sell")
    price: float
    amount: float
    status: bool = Field(..., description="True if closed/filled, False otherwise")
