from enum import StrEnum


class PositionType(StrEnum):
    LONG = "long"
    SHORT = "short"


class PositionStatus(StrEnum):
    OPENED = "opened"
    CLOSED = "closed"


class PositionCloseReason(StrEnum):
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    OPPOSITE_SIGNAL = "opposite_signal"
    STRATEGY = "strategy"
    TIMEOUT = "timeout"
    MANUAL = "manual"
