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
    PNL_STOP_LOSS = "pnl_stop_loss"  # Арбитраж: суммарный PnL достиг лимита убытка
    PNL_TAKE_PROFIT = "pnl_take_profit"  # Арбитраж: суммарный PnL достиг цели прибыли
    OPPOSITE_SIGNAL = "opposite_signal"
    STRATEGY = "strategy"
    TIMEOUT = "timeout"
    MANUAL = "manual"
