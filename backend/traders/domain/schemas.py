from enum import Enum


class PositionStatus(str, Enum):
    OPENED = "opened"
    CLOSED = "closed"
    PENDING = "pending"
