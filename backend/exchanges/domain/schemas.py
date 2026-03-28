from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel

from core.utils.registry import Registry


class ExchangeRegistry(Registry):
    pass


def parse_decimal(value: Any, default: Decimal) -> Decimal:
    """Безопасное преобразование в Decimal."""
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return default


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


class TradingPair(BaseModel):
    name: str
    symbol: str
    type: MarketType
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    fee_percent: Decimal | None = None
    taker_fee: Decimal = Decimal("0")
    maker_fee: Decimal = Decimal("0")
    max_leverage: Decimal = Decimal("1")


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
