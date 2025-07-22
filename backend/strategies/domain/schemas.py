from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

from exchanges.domain.schemas import Candle


class SignalType(str, Enum):
    BUY = "buy"
    SELL = "sell"
    WAIT = "wait"


class TraderSignal(BaseModel):
    timestamp: datetime
    type: SignalType
    price: Decimal


class RenckoBrick(BaseModel):
    timestamp: datetime
    type: Literal["up", "down", "first"]
    open: Optional[Decimal]
    close: Optional[Decimal]
    low: Optional[Decimal]
    high: Optional[Decimal]
