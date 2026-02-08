from enum import StrEnum


class SignalType(StrEnum):
    """Типы торговых сигналов."""

    BUY = "buy"
    SELL = "sell"
    WAIT = "wait"

    @classmethod
    def choices(cls):
        return [(member.value, member.value) for member in cls]
