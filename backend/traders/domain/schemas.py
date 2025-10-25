from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional, Tuple

from exchanges.domain import Candle
from pydantic import BaseModel
from risk_managers.domain import PositionCloseReason, PositionStatus, PositionType
from strategies.domain import TraderSignal


class TraderState(BaseModel):
    timestamp: datetime
    candle: Candle
    signal: TraderSignal


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
    total_fee: Optional[Decimal] = None
    data: Optional[dict] = None

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
            if self.pnl is not None and self.open_cost is not None and self.open_cost != 0
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

    def should_be_closed(
        self,
        price: Decimal | None = None,
    ) -> Tuple[bool, PositionCloseReason | None]:

        if self.status != PositionStatus.OPENED:
            return False, None

        if price:
            should_close, close_reason = self.should_be_closed_by_take_profit(
                price=price
            )
            if should_close:
                return should_close, close_reason

            should_close, close_reason = self.should_be_closed_by_stop_loss(price=price)
            if should_close:
                return should_close, close_reason

        return False, None
