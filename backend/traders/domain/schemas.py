from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum, StrEnum
from typing import Any, Literal

from pydantic import BaseModel

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


class TraderSignal(BaseModel):
    """Торговый сигнал трейдера."""

    id: int | None = None
    timestamp: datetime
    price: Decimal
    candle: ExchangeCandle
    type: SignalType
    data: dict[str, Any] = {}


class RenkoBrick(BaseModel):
    timestamp: datetime
    type: Literal["up", "down", "first"]
    open: Decimal | None
    close: Decimal | None
    low: Decimal | None = None
    high: Decimal | None = None


class RenkoState(BaseModel):
    timestamp: datetime
    bricks: list["RenkoBrick"]


class MFIState(BaseModel):
    timestamp: datetime
    mfi_value: float


class MoneyFlowIndexStrategyData(BaseModel):
    """Данные MFI сигнала."""

    mfi_value: float


class RenkoData(BaseModel):
    """Данные Renko сигнала."""

    bricks: list[RenkoBrick]


class StochasticData(BaseModel):
    k_value: float
    d_value: float | None


class DonchianCrossoverData(BaseModel):
    fast_upper: float
    fast_lower: float
    slow_upper: float
    slow_lower: float
    candle_low: float
    candle_high: float


class MovingAverageCrossoverData(BaseModel):
    fast_avg: float
    slow_avg: float


class GridTradingData(BaseModel):
    avg: float
    candle_close: float
    narrow_grid_up: float
    narrow_grid_down: float
    wide_grid_up: float
    wide_grid_down: float


class MeanReversionChannelData(BaseModel):
    """Данные стратегии Mean Reversion Channel (коридор по SMA +/- k * sigma)."""

    sma: float
    std: float
    upper: float
    lower: float
    period: int
    sigma_mult: float
    threshold: float
    
class SMAGreenData(BaseModel):
    timestamp: datetime
    sma: float



class TraderStatus(Enum):
    ENABLED = "enabled"
    REBOOTING = "rebooting"
    CLEARING = "clearing"
    DISABLED = "disabled"
    PAUSED = "paused"
    ERROR = "error"


class TraderPosition(BaseModel):
    id: int | None = None
    type: PositionType
    status: PositionStatus
    total_fee: Decimal = Decimal("0")
    open_price: Decimal | None = None
    close_price: Decimal | None = None
    open_amount: Decimal | None = None
    close_amount: Decimal | None = None
    open_cost: Decimal | None = None
    close_cost: Decimal | None = None
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    recalculated_at: datetime | None = None
    close_reason: PositionCloseReason | None = None
    orders: list[ExchangeClientOrder] = []
    open_signal: TraderSignal | None = None
    close_signal: TraderSignal | None = None

    @property
    def pnl(self) -> Decimal | None:
        """PnL (с учётом комиссии)."""
        if self.status != PositionStatus.CLOSED:
            return None
        if self.close_cost is None or self.open_cost is None:
            return None
        if self.type == PositionType.LONG:
            return self.close_cost - self.open_cost - self.total_fee
        elif self.type == PositionType.SHORT:
            return self.open_cost - self.close_cost - self.total_fee
        return None

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
    def rr(self) -> Decimal | None:
        risk = None
        reward = None
        if self.open_price is None:
            return None
        if self.stop_loss is not None:
            risk = abs(self.open_price - self.stop_loss)
        if self.take_profit is not None:
            reward = abs(self.take_profit - self.open_price)
        if risk is None or reward is None or risk == 0:
            return None
        try:
            return reward / risk
        except (ZeroDivisionError, InvalidOperation):
            return None

    @property
    def take_profit_pct(self) -> Decimal | None:
        if self.take_profit is None or self.open_price is None:
            return None

        if self.type == PositionType.LONG:
            return (self.take_profit - self.open_price) / self.open_price * 100
        elif self.type == PositionType.SHORT:
            return (self.open_price - self.take_profit) / self.open_price * 100
        return None

    @property
    def stop_loss_pct(self):
        if self.stop_loss is None or self.open_price is None:
            return None

        if self.type == PositionType.LONG:
            return (self.stop_loss - self.open_price) / self.open_price * 100
        elif self.type == PositionType.SHORT:
            return (self.open_price - self.stop_loss) / self.open_price * 100
        return None

    @property
    def is_closed(self) -> bool:
        return self.status == PositionStatus.CLOSED

    def should_be_closed_by_take_profit(self, price: Decimal) -> bool:
        return self.take_profit is not None and (
            (self.type == PositionType.LONG and price >= self.take_profit)
            or (self.type == PositionType.SHORT and price <= self.take_profit)
        )

    def should_be_closed_by_stop_loss(self, price: Decimal) -> bool:
        return self.stop_loss is not None and (
            (self.type == PositionType.LONG and price <= self.stop_loss)
            or (self.type == PositionType.SHORT and price >= self.stop_loss)
        )


class TraderError(BaseModel):
    """Ошибка трейдера."""

    id: int | None = None
    timestamp: datetime
    message: str
    type: str | None = None
    traceback: str | None = None


# ==================== Optimizer Schemas ====================


class OptimizationResult(BaseModel):
    value: float
    params: dict[str, Any]


class OptimizerStatus(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    REBOOTING = "rebooting"
    ERROR = "error"


class TraderOptimizationResult(BaseModel):
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
