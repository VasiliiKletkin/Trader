from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Callable, Optional, Tuple

from pydantic import BaseModel
from core.domain.types import SignalType, TraderSignal


class PositionType(str, Enum):
    LONG = "long"
    SHORT = "short"


class PositionStatus(str, Enum):
    OPENED = "opened"
    CLOSED = "closed"


class PositionCloseReason(str, Enum):
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    OPPOSITE_SIGNAL = "opposite_signal"
    STRATEGY = "strategy"
    TIMEOUT = "timeout"
    MANUAL = "manual"


class TraderPosition(BaseModel):
    type: PositionType
    status: PositionStatus
    amount: Decimal
    open_price: Optional[Decimal] = None
    close_price: Optional[Decimal] = None
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    recalculated_at: Optional[datetime] = None
    close_reason: Optional[PositionCloseReason] = None
    data: Optional[dict] = None

    @property
    def pnl(self) -> Optional[Decimal]:
        if self.status != PositionStatus.CLOSED or self.close_price is None:
            return None

        if self.type == PositionType.LONG:
            return (self.close_price - self.open_price) * self.amount
        if self.type == PositionType.SHORT:
            return (self.open_price - self.close_price) * self.amount

    @property
    def rr(self) -> Optional[Decimal]:
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
    def take_profit_pct(self) -> Optional[Decimal]:
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
    def close_value(self) -> Optional[Decimal]:
        if self.close_price:
            return self.amount * self.close_price

    @property
    def open_value(self) -> Optional[Decimal]:
        if self.open_price:
            return self.open_price * self.amount

    def should_be_closed(
        self,
        signal: TraderSignal | None = None,
        price: Decimal | None = None,
        should_be_closed_by_strategy: Callable | None = None,
    ) -> Tuple[bool, PositionCloseReason | None]:
        if self.status != PositionStatus.OPENED:
            return False, None

        if signal:
            # Противоположний сигнал
            if (self.type == PositionType.LONG and signal.type == SignalType.SELL) or (
                self.type == PositionType.SHORT and signal.type == SignalType.BUY
            ):
                return True, PositionCloseReason.OPPOSITE_SIGNAL

        if price:
            # Стоп-лосс
            if self.stop_loss is not None:
                if (self.type == PositionType.LONG and price <= self.stop_loss) or (
                    self.type == PositionType.SHORT and price >= self.stop_loss
                ):
                    return True, PositionCloseReason.STOP_LOSS

            # Тейк-профит
            if self.take_profit is not None:
                if (self.type == PositionType.LONG and price >= self.take_profit) or (
                    self.type == PositionType.SHORT and price <= self.take_profit
                ):
                    return True, PositionCloseReason.TAKE_PROFIT

        # Стратегия закрытия
        if should_be_closed_by_strategy:
            if should_be_closed_by_strategy(self, signal.data, self.data):
                return True, PositionCloseReason.STRATEGY
        return False, None
