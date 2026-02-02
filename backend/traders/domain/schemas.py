from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel
from risk_managers.domain import PositionCloseReason, PositionStatus, PositionType
from exchange_clients.domain import ExchangeClientOrder


class TraderStatus(Enum):
    ENABLED = "enabled"
    REBOOTING = "rebooting"
    DISABLED = "disabled"
    PAUSED = "paused"
    ERROR = "error"


class TraderPosition(BaseModel):
    id: Optional[int] = None
    type: PositionType
    status: PositionStatus
    amount: Decimal
    total_fee: Decimal = Decimal("0")
    open_price: Optional[Decimal] = None
    close_price: Optional[Decimal] = None
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    recalculated_at: Optional[datetime] = None
    close_reason: Optional[PositionCloseReason] = None
    orders: List[ExchangeClientOrder] = []

    @property
    def pnl(self) -> Optional[Decimal]:
        if self.status != PositionStatus.CLOSED or self.close_price is None:
            return None

        gross_pnl = None
        if self.type == PositionType.LONG:
            gross_pnl = (self.close_price - self.open_price) * self.amount
        elif self.type == PositionType.SHORT:
            gross_pnl = (self.open_price - self.close_price) * self.amount

        if gross_pnl is not None:
            return gross_pnl - (self.total_fee or 0)
        return None

    @property
    def pnl_pct(self) -> Optional[Decimal]:
        return (
            100 * self.pnl / self.open_cost
            if self.pnl is not None
            and self.open_cost is not None
            and self.open_cost != 0
            else None
        )

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
    def close_cost(self) -> Optional[Decimal]:
        if self.close_price:
            return self.amount * self.close_price

    @property
    def open_cost(self) -> Optional[Decimal]:
        if self.open_price:
            return self.open_price * self.amount

    @property
    def is_closed(self) -> bool:
        return self.status == PositionStatus.CLOSED

    def should_be_closed_by_take_profit(self, price: Decimal) -> bool:
        if self.take_profit is not None:
            if (self.type == PositionType.LONG and price >= self.take_profit) or (
                self.type == PositionType.SHORT and price <= self.take_profit
            ):
                return True
        return False

    def should_be_closed_by_stop_loss(self, price: Decimal) -> bool:
        if self.stop_loss is not None:
            if (self.type == PositionType.LONG and price <= self.stop_loss) or (
                self.type == PositionType.SHORT and price >= self.stop_loss
            ):
                return True
        return False


class ArbitrageTraderError(BaseModel):
    """Ошибка арбитражного трейдера."""

    id: Optional[int] = None
    timestamp: datetime
    message: str
    type: Optional[str] = None
    traceback: Optional[str] = None


class ArbitrageTraderPosition(BaseModel):

    id: Optional[int] = None
    type: PositionType
    first_type: PositionType
    second_type: PositionType
    status: PositionStatus
    amount: Decimal
    total_fee: Decimal = Decimal("0")

    first_open_price: Optional[Decimal] = None
    first_close_price: Optional[Decimal] = None
    second_open_price: Optional[Decimal] = None
    second_close_price: Optional[Decimal] = None

    first_orders: List[ExchangeClientOrder] = []
    second_orders: List[ExchangeClientOrder] = []

    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    close_reason: Optional[PositionCloseReason] = None

    @property
    def first_pnl(self) -> Optional[Decimal]:
        """PnL по первой бирже."""
        if self.first_open_price is None or self.first_close_price is None:
            return None
        if self.first_type == PositionType.LONG:
            return (self.first_close_price - self.first_open_price) * self.amount
        elif self.first_type == PositionType.SHORT:
            return (self.first_open_price - self.first_close_price) * self.amount
        return None

    @property
    def second_pnl(self) -> Optional[Decimal]:
        """PnL по второй бирже."""
        if self.second_open_price is None or self.second_close_price is None:
            return None
        if self.second_type == PositionType.LONG:
            return (self.second_close_price - self.second_open_price) * self.amount
        elif self.second_type == PositionType.SHORT:
            return (self.second_open_price - self.second_close_price) * self.amount
        return None

    @property
    def pnl(self) -> Optional[Decimal]:
        """Общий PnL по обеим биржам."""
        if self.status != PositionStatus.CLOSED:
            return None
        if self.first_pnl is None or self.second_pnl is None:
            return None
        return self.first_pnl + self.second_pnl - (self.total_fee or 0)

    @property
    def pnl_pct(self) -> Optional[Decimal]:
        return (
            100 * self.pnl / self.open_cost
            if self.pnl is not None
            and self.open_cost is not None
            and self.open_cost != 0
            else None
        )

    @property
    def first_open_cost(self) -> Optional[Decimal]:
        if self.first_open_price:
            return self.first_open_price * self.amount

    @property
    def second_open_cost(self) -> Optional[Decimal]:
        if self.second_open_price:
            return self.second_open_price * self.amount

    @property
    def open_cost(self) -> Optional[Decimal]:
        """Суммарная стоимость открытия позиций на обеих биржах."""
        first = self.first_open_cost or Decimal("0")
        second = self.second_open_cost or Decimal("0")
        if not first and not second:
            return None
        return first + second

    @property
    def first_close_cost(self) -> Optional[Decimal]:
        if self.first_close_price:
            return self.first_close_price * self.amount

    @property
    def second_close_cost(self) -> Optional[Decimal]:
        if self.second_close_price:
            return self.second_close_price * self.amount

    @property
    def close_cost(self) -> Optional[Decimal]:
        """Суммарная стоимость закрытия позиций на обеих биржах."""
        first = self.first_close_cost or Decimal("0")
        second = self.second_close_cost or Decimal("0")
        if not first and not second:
            return None
        return first + second

    @property
    def is_closed(self) -> bool:
        return self.status == PositionStatus.CLOSED
