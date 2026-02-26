from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum, StrEnum
from typing import Any, Self

from pydantic import BaseModel, model_validator

from arbitrage_traders.domain.exceptions import CandleDesyncError
from exchange_clients.domain import ExchangeClientOrder
from exchanges.domain import ExchangeCandle


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


class SignalType(StrEnum):
    """Типы торговых сигналов."""

    BUY = "buy"
    SELL = "sell"
    WAIT = "wait"


class TraderStatus(Enum):
    ENABLED = "enabled"
    REBOOTING = "rebooting"
    DISABLED = "disabled"
    PAUSED = "paused"
    ERROR = "error"


class OptimizerStatus(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    REBOOTING = "rebooting"
    ERROR = "error"


class ArbitrageCandle(BaseModel):
    """Пара свечей с двух бирж для арбитражной торговли."""

    left: ExchangeCandle
    right: ExchangeCandle

    @model_validator(mode="after")
    def validate_timestamps(self) -> Self:
        if self.left.timestamp != self.right.timestamp:
            raise CandleDesyncError(
                f"Timestamps свечей не совпадают: "
                f"left={self.left.timestamp}, right={self.right.timestamp}"
            )
        return self

    @property
    def timestamp(self) -> datetime:
        return self.left.timestamp

    @property
    def spread(self) -> float:
        """Спред между биржами в процентах."""
        if self.right.close == 0:
            raise ValueError("Цена на второй бирже не может быть нулевой")
        return float((self.left.close - self.right.close) / self.right.close * 100)


class ArbitrageTraderError(BaseModel):
    """Ошибка арбитражного трейдера."""

    id: int | None = None
    timestamp: datetime
    message: str
    type: str | None = None
    traceback: str | None = None


class ArbitrageTraderPosition(BaseModel):
    id: int | None = None
    type: PositionType
    left_type: PositionType
    right_type: PositionType
    status: PositionStatus
    amount: Decimal
    left_total_fee: Decimal = Decimal("0")
    right_total_fee: Decimal = Decimal("0")

    left_open_price: Decimal | None = None
    left_close_price: Decimal | None = None
    right_open_price: Decimal | None = None
    right_close_price: Decimal | None = None

    left_orders: list[ExchangeClientOrder] = []
    right_orders: list[ExchangeClientOrder] = []

    opened_at: datetime | None = None
    closed_at: datetime | None = None
    close_reason: PositionCloseReason | None = None

    @property
    def total_fee(self) -> Decimal:
        """Общая комиссия по обеим биржам."""
        return self.left_total_fee + self.right_total_fee

    @property
    def left_pnl(self) -> Decimal | None:
        """PnL по первой бирже (с учётом комиссии)."""
        if self.left_open_price is None or self.left_close_price is None:
            return None
        if self.left_type == PositionType.LONG:
            return (
                self.left_close_price - self.left_open_price
            ) * self.amount - self.left_total_fee
        elif self.left_type == PositionType.SHORT:
            return (
                self.left_open_price - self.left_close_price
            ) * self.amount - self.left_total_fee
        return None

    @property
    def right_pnl(self) -> Decimal | None:
        """PnL по второй бирже (с учётом комиссии)."""
        if self.right_open_price is None or self.right_close_price is None:
            return None
        if self.right_type == PositionType.LONG:
            return (
                self.right_close_price - self.right_open_price
            ) * self.amount - self.right_total_fee
        elif self.right_type == PositionType.SHORT:
            return (
                self.right_open_price - self.right_close_price
            ) * self.amount - self.right_total_fee
        return None

    @property
    def pnl(self) -> Decimal | None:
        """Общий PnL по обеим биржам."""
        if self.status != PositionStatus.CLOSED:
            return None
        if self.left_pnl is None or self.right_pnl is None:
            return None
        return self.left_pnl + self.right_pnl

    @property
    def pnl_pct(self) -> Decimal | None:
        return (
            100 * self.pnl / self.open_cost
            if self.pnl is not None
            and self.open_cost is not None
            and self.open_cost != 0
            else None
        )

    @property
    def left_open_cost(self) -> Decimal | None:
        if self.left_open_price:
            return self.left_open_price * self.amount
        return None

    @property
    def right_open_cost(self) -> Decimal | None:
        if self.right_open_price:
            return self.right_open_price * self.amount
        return None

    @property
    def open_cost(self) -> Decimal | None:
        """Суммарная стоимость открытия позиций на обеих биржах."""
        first = self.left_open_cost or Decimal("0")
        second = self.right_open_cost or Decimal("0")
        if not first and not second:
            return None
        return first + second

    @property
    def left_close_cost(self) -> Decimal | None:
        if self.left_close_price:
            return self.left_close_price * self.amount
        return None

    @property
    def right_close_cost(self) -> Decimal | None:
        if self.right_close_price:
            return self.right_close_price * self.amount
        return None

    @property
    def close_cost(self) -> Decimal | None:
        """Суммарная стоимость закрытия позиций на обеих биржах."""
        first = self.left_close_cost or Decimal("0")
        second = self.right_close_cost or Decimal("0")
        if not first and not second:
            return None
        return first + second

    @property
    def is_closed(self) -> bool:
        return self.status == PositionStatus.CLOSED


class ArbitrageTraderSignal(BaseModel):
    """Торговый сигнал арбитражного трейдера."""

    id: int | None = None
    timestamp: datetime
    left_type: SignalType
    right_type: SignalType
    left_price: Decimal
    right_price: Decimal
    left_candle: ExchangeCandle
    right_candle: ExchangeCandle
    data: dict[str, Any] = {}


class SpreadReversionArbitrageData(BaseModel):
    """Данные стратегии возврата спреда."""

    spread: float
    price_first: float
    price_second: float


class CrossSpreadArbitrageData(BaseModel):
    """Данные стратегии с перекрёстным выходом."""

    spread: float
    price_first: float
    price_second: float


class OptimizationResult(BaseModel):
    value: float
    params: dict[str, Any]


class ArbitrageTraderOptimizationResult(BaseModel):
    """Результат оптимизации арбитражного трейдера."""

    pnl: Decimal
    win_rate: Decimal
    avg_candles_per_position: Decimal
    pnl_r2: Decimal
    roi: Decimal
    sharpe: Decimal
    total_positions: int
    strategy_arguments: dict[str, Any]
    risk_manager_arguments: dict[str, Any]
    duration: timedelta
