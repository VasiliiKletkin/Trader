from enum import Enum
from pydantic import BaseModel
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict


class SignalType(str, Enum):
    """Типы торговых сигналов."""

    BUY = "buy"
    SELL = "sell"
    WAIT = "wait"

    @classmethod
    def choices(cls):
        return [(member.value, member.value) for member in cls]


class TraderSignal(BaseModel):
    """Торговый сигнал трейдера."""

    timestamp: datetime
    type: SignalType
    price: Decimal
    data: Dict[str, Any] = {}
