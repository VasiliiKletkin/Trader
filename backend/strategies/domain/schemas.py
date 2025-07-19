from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

from exchanges.domain.schemas import Candle as CandleDTO


class SignalType(str, Enum):
    BUY = "buy"
    SELL = "sell"
    WAIT = "wait"


class BrickDTO(BaseModel):
    """
    Модель для описания одного кирпичика Renko.
    """

    timestamp: Optional[datetime] = Field(
        default=None,
        description="Временная метка, связанная с кирпичиком (например, дата или UNIX-время)",
    )
    type: Literal["up", "down", "first"] = Field(
        ...,
        description="Тип кирпичика: 'up', 'down' или 'first'",
    )
    open: Optional[Decimal] = Field(
        default=None,
        description="Цена открытия кирпичика",
    )
    close: Optional[Decimal] = Field(
        default=None,
        description="Цена закрытия кирпичика",
    )
    low: Optional[Decimal] = Field(
        default=None,
        description="Минимальная цена тени (вниз), если есть",
    )
    high: Optional[Decimal] = Field(
        default=None,
        description="Максимальная цена тени (вверх), если есть",
    )


class MFIDTO(BaseModel):
    """
    Модель для описания значения индикатора MFI.
    """

    candle: CandleDTO = Field(
        ...,
        description="Связанный объект свечи, к которой относится значение MFI",
    )
    value: Decimal = Field(
        ...,
        description="Значение индикатора MFI",
    )
