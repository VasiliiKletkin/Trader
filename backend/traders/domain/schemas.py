from enum import Enum


class PositionStatusDomain(str, Enum):
    OPENED = "opened"
    CLOSED = "closed"
    PENDING = "pending"
