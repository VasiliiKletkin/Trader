from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum

from pydantic import BaseModel

from exchange_clients.domain import ExchangeClientOrder
from risk_managers.domain import PositionCloseReason, PositionStatus, PositionType


class TraderStatus(Enum):
    ENABLED = "enabled"
    REBOOTING = "rebooting"
    DISABLED = "disabled"
    PAUSED = "paused"
    ERROR = "error"


class TraderPosition(BaseModel):
    id: int | None = None
    type: PositionType
    status: PositionStatus
    amount: Decimal
    total_fee: Decimal = Decimal("0")
    open_price: Decimal | None = None
    close_price: Decimal | None = None
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    recalculated_at: datetime | None = None
    close_reason: PositionCloseReason | None = None
    orders: list[ExchangeClientOrder] = []

    @property
    def pnl(self) -> Decimal | None:
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
    def close_cost(self) -> Decimal | None:
        if self.close_price:
            return self.amount * self.close_price

    @property
    def open_cost(self) -> Decimal | None:
        if self.open_price:
            return self.open_price * self.amount

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
    total_fee: Decimal = Decimal("0")

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
    def left_pnl(self) -> Decimal | None:
        """PnL по первой бирже."""
        if self.left_open_price is None or self.left_close_price is None:
            return None
        if self.left_type == PositionType.LONG:
            return (self.left_close_price - self.left_open_price) * self.amount
        elif self.left_type == PositionType.SHORT:
            return (self.left_open_price - self.left_close_price) * self.amount
        return None

    @property
    def right_pnl(self) -> Decimal | None:
        """PnL по второй бирже."""
        if self.right_open_price is None or self.right_close_price is None:
            return None
        if self.right_type == PositionType.LONG:
            return (self.right_close_price - self.right_open_price) * self.amount
        elif self.right_type == PositionType.SHORT:
            return (self.right_open_price - self.right_close_price) * self.amount
        return None

    @property
    def pnl(self) -> Decimal | None:
        """Общий PnL по обеим биржам."""
        if self.status != PositionStatus.CLOSED:
            return None
        if self.left_pnl is None or self.right_pnl is None:
            return None
        return self.left_pnl + self.right_pnl - (self.total_fee or 0)

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

    @property
    def right_open_cost(self) -> Decimal | None:
        if self.right_open_price:
            return self.right_open_price * self.amount

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

    @property
    def right_close_cost(self) -> Decimal | None:
        if self.right_close_price:
            return self.right_close_price * self.amount

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
