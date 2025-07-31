from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel


class RenkoState(BaseModel):
    timestamp: datetime
    bricks: list["RenkoBrick"]


class RenkoBrick(BaseModel):
    timestamp: datetime
    type: Literal["up", "down", "first"]
    open: Optional[Decimal]
    close: Optional[Decimal]
    low: Optional[Decimal] = None
    high: Optional[Decimal] = None


class MFIState(BaseModel):
    timestamp: datetime
    mfi_value: float


class MFIData(BaseModel):
    """Данные MFI сигнала."""

    mfi_value: float


class RenkoData(BaseModel):
    """Данные Renko сигнала."""

    bricks: list[RenkoBrick]
