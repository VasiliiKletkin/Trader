from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Optional, Tuple

from pydantic import BaseModel


class PositionType(str, Enum):
    LONG = "long"
    SHORT = "short"


class PositionStatus(str, Enum):
    OPENED = "opened"
    CLOSED = "closed"


class PositionCloseReason(str, Enum):
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    OPPOSITE_SIGNAL = "opposite_signal"
    STRATEGY = "strategy"
    TIMEOUT = "timeout"
    MANUAL = "manual"
