from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class PositionType(str, Enum):
    LONG = "long"
    SHORT = "short"


class TraderPosition(BaseModel):
    trading_pair: str = Field(..., description="Trading pair for the position")
    type: PositionType = Field(..., description="Type of the position (long or short)")
    entry_price: Decimal = Field(..., description="Entry price of the position")
    amount: Decimal = Field(..., description="Amount of the asset in the position")
    open_timestamp: datetime = Field(
        ..., description="Timestamp when the position was opened"
    )
    close_timestamp: Optional[datetime] = Field(
        None, description="Timestamp when the position was closed"
    )
    status: str = Field(..., description="Status of the position (opened or closed)")

    @property
    def pnl(self) -> Optional[Decimal]:
        """
        Calculate the profit and loss of the position.
        Returns None if the position is still open.
        """
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
        signal: SignalType | None,
        price: Decimal | None,
    ) -> bool:
        """
        Determines if the position should be closed based on its status and timestamps.
        """
        if self.status != PositionStatus.OPENED:
            return False

        if signal:
            # Противоположний сигнал
            if (self.type == PositionType.LONG and signal == SignalType.SELL) or (
                self.type == PositionType.SHORT and signal == SignalType.BUY
            ):
                return True

        if price:
            # Стоп-лосс
            if self.stop_loss is not None:
                if (self.type == PositionType.LONG and price <= self.stop_loss) or (
                    self.type == PositionType.SHORT and price >= self.stop_loss
                ):
                    return True

            # Тейк-профит
            if self.take_profit is not None:
                if (self.type == PositionType.LONG and price >= self.take_profit) or (
                    self.type == PositionType.SHORT and price <= self.take_profit
                ):
                    return True

        return False
