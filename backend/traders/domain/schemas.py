from datetime import datetime
from enum import Enum

from exchanges.domain import Candle
from pydantic import BaseModel
from strategies.domain import TraderSignal


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
