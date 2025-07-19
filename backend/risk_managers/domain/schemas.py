from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Optional

from pydantic import BaseModel
from strategies.domain.schemas import SignalType


class DomainPositionType(str, Enum):
    LONG = "long"
    SHORT = "short"


class DomainPositionStatus(str, Enum):
    OPENED = "opened"
    CLOSED = "closed"


class DomainTraderPosition(BaseModel):
    type: DomainPositionType
    status: DomainPositionStatus
    amount: Decimal
    open_price: Optional[Decimal] = None
    close_price: Optional[Decimal] = None
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None

    @property
    def pnl(self) -> Optional[Decimal]:
        if self.status != DomainPositionStatus.CLOSED or self.close_price is None:
            return None

        if self.type == DomainPositionType.LONG:
            return (self.close_price - self.open_price) * self.amount
        if self.type == DomainPositionType.SHORT:
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

        if self.type == DomainPositionType.LONG:
            return (self.take_profit - self.open_price) / self.open_price * 100
        elif self.type == DomainPositionType.SHORT:
            return (self.open_price - self.take_profit) / self.open_price * 100
        return None

    @property
    def stop_loss_pct(self):
        if self.stop_loss is None or self.open_price is None:
            return None

        if self.type == DomainPositionType.LONG:
            return (self.stop_loss - self.open_price) / self.open_price * 100
        elif self.type == DomainPositionType.SHORT:
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
        signal: SignalType | None,
        price: Decimal | None,
    ) -> bool:
        if self.status != DomainPositionStatus.OPENED:
            return False

        if signal:
            # Противоположний сигнал
            if (self.type == DomainPositionType.LONG and signal == SignalType.SELL) or (
                self.type == DomainPositionType.SHORT and signal == SignalType.BUY
            ):
                return True

        if price:
            # Стоп-лосс
            if self.stop_loss is not None:
                if (
                    self.type == DomainPositionType.LONG and price <= self.stop_loss
                ) or (
                    self.type == DomainPositionType.SHORT and price >= self.stop_loss
                ):
                    return True

            # Тейк-профит
            if self.take_profit is not None:
                if (
                    self.type == DomainPositionType.LONG and price >= self.take_profit
                ) or (
                    self.type == DomainPositionType.SHORT and price <= self.take_profit
                ):
                    return True

        return False
