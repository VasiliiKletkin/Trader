from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, field_validator

from core.utils.registry import Registry


class ExchangeRegistry(Registry):
    pass


MAX_DECIMAL = Decimal("999999999999")  # max 12 цифр целой части (NUMERIC 30,18)


class Exchange(BaseModel):
    name: str
    client_class_name: str
    max_candles_per_request: int = 999
    timeout: int = 30000
    rate_limit: int = 500

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        ExchangeRegistry.register(cls)

    async def load_markets(self) -> list["TradingPair"]:
        """Загрузить торговые пары с биржи через ccxt."""
        raise NotImplementedError


class Candle(BaseModel):
    dt_unix: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    @property
    def timestamp(self) -> datetime:
        return datetime.fromtimestamp(self.dt_unix / 1000, tz=UTC)

    @property
    def type(self) -> Literal["up", "down"]:
        return "up" if self.close >= self.open else "down"


class ExchangeCandle(Candle):
    id: int


class MarketType(StrEnum):
    FUTURES = "futures"
    SPOT = "spot"


def _safe_decimal(value: Any) -> Decimal | None:
    """Безопасное преобразование в Decimal. None при невалидных значениях."""
    if value is None:
        return None
    try:
        result = Decimal(str(value))
        if not result.is_finite() or abs(result) > MAX_DECIMAL:
            return None
        return result
    except (InvalidOperation, ValueError):
        return None


class TradingPair(BaseModel):
    name: str
    symbol: str
    type: MarketType
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    taker_fee: Decimal = Decimal("0.001")
    maker_fee: Decimal = Decimal("0.001")
    max_leverage: Decimal = Decimal("1.0")

    @field_validator("min_amount", "max_amount", mode="before")
    @classmethod
    def validate_nullable_decimal(cls, v: Any) -> Decimal | None:
        return _safe_decimal(v)

    @field_validator("taker_fee", "maker_fee", "max_leverage", mode="before")
    @classmethod
    def validate_required_decimal(cls, v: Any, info: Any) -> Decimal:
        result = _safe_decimal(v)
        if result is not None:
            return result
        defaults = {
            "taker_fee": Decimal("0.001"),
            "maker_fee": Decimal("0.001"),
            "max_leverage": Decimal("1.0"),
        }
        return defaults[info.field_name]


class Timeframe(StrEnum):
    ONE_MINUTE = "1m"
    FIVE_MINUTES = "5m"
    FIFTEEN_MINUTES = "15m"
    ONE_HOUR = "1h"
    FOUR_HOURS = "4h"
    ONE_DAY = "1d"
    ONE_WEEK = "1w"

    def timedelta(self) -> timedelta:
        return {
            self.ONE_MINUTE: timedelta(minutes=1),
            self.FIVE_MINUTES: timedelta(minutes=5),
            self.FIFTEEN_MINUTES: timedelta(minutes=15),
            self.ONE_HOUR: timedelta(hours=1),
            self.FOUR_HOURS: timedelta(hours=4),
            self.ONE_DAY: timedelta(days=1),
            self.ONE_WEEK: timedelta(weeks=1),
        }[self]
