from datetime import datetime
from enum import Enum

from core.domain.types import TraderSignal
from exchanges.domain import Candle
from pydantic import BaseModel


class TraderState(BaseModel):
    timestamp: datetime
    candle: Candle
    signal: TraderSignal


class PositionStatus(str, Enum):
    OPENED = "opened"
    CLOSED = "closed"
    PENDING = "pending"


class TraderStatus(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    ERROR = "error"
    REBOOTING = "rebooting"
