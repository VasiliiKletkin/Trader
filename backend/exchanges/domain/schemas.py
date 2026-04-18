from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel

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


def safe_decimal(value: Any) -> Decimal | None:
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


class TradingPair(BaseModel, frozen=True):
    is_active: bool = True
    name: str
    symbol: str
    base_currency: str
    quote_currency: str
    settle_currency: str
    market_type: MarketType
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    min_cost: Decimal | None = None
    max_cost: Decimal | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    price_precision: Decimal | None = None
    amount_precision: Decimal | None = None
    taker_fee: Decimal = Decimal("0.001")
    maker_fee: Decimal = Decimal("0.001")
    min_leverage: Decimal = Decimal("1.0")
    max_leverage: Decimal = Decimal("1.0")
    is_linear: bool | None = None
    contract_size: Decimal | None = None
    supports_cross_margin: bool = False
    supports_isolated_margin: bool = False

    def quantize_amount(self, amount: Decimal) -> Decimal:
        """Округлить amount вниз до кратного amount_precision (step_size биржи)."""
        if not self.amount_precision or self.amount_precision <= 0:
            return amount
        return (amount // self.amount_precision) * self.amount_precision

    def quantize_price(self, price: Decimal) -> Decimal:
        """Округлить price вниз до кратного price_precision (tick_size биржи)."""
        if not self.price_precision or self.price_precision <= 0:
            return price
        return (price // self.price_precision) * self.price_precision

    def fit_amount(self, amount: Decimal, price: Decimal) -> Decimal | None:
        """
        Квантует amount и проверяет соответствие лимитам биржи.

        Применяет: quantize_amount → clamp min/max_amount → проверка min/max_cost.
        Возвращает подогнанный amount или None, если cost вне допустимых границ
        или amount невалиден.
        """
        amount = self.quantize_amount(amount)
        if amount <= 0:
            return None
        if self.min_amount and amount < self.min_amount:
            amount = self.min_amount
        if self.max_amount and amount > self.max_amount:
            amount = self.max_amount
        cost = amount * price
        if self.min_cost and cost < self.min_cost:
            return None
        if self.max_cost and cost > self.max_cost:
            return None
        return amount


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
