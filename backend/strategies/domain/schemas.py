from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel
from exchanges.domain import Candle


class SignalType(str, Enum):
    """Типы торговых сигналов."""

    BUY = "buy"
    SELL = "sell"
    WAIT = "wait"


class TraderSignal(BaseModel):
    """Торговый сигнал трейдера."""
    id: Optional[int] = None
    timestamp: datetime
    price: Decimal
    type: SignalType
    data: Dict[str, Any] = {}


class RenkoBrick(BaseModel):
    timestamp: datetime
    type: Literal["up", "down", "first"]
    open: Optional[Decimal]
    close: Optional[Decimal]
    low: Optional[Decimal] = None
    high: Optional[Decimal] = None


class RenkoState(BaseModel):
    timestamp: datetime
    bricks: list["RenkoBrick"]


class MFIState(BaseModel):
    timestamp: datetime
    mfi_value: float


class MoneyFlowIndexStrategyData(BaseModel):
    """Данные MFI сигнала."""

    mfi_value: float


class RenkoData(BaseModel):
    """Данные Renko сигнала."""

    bricks: list[RenkoBrick]


class StochasticData(BaseModel):
    k_value: float
    d_value: Optional[float]


class DonchianCrossoverData(BaseModel):
    fast_upper: float
    fast_lower: float
    slow_upper: float
    slow_lower: float
