from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from decimal import Decimal
from pydantic import BaseModel


class Candle(BaseModel):
    dt_unix: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    @property
    def timestamp(self) -> datetime:
        return datetime.fromtimestamp(self.dt_unix / 1000, tz=timezone.utc)

    @property
    def type(self) -> Literal["up", "down"]:
        return "up" if self.close >= self.open else "down"


class OrderStatus(str, Enum):
    OPENED = "opened"
    CLOSED = "closed"
    CANCELED = "canceled"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class TradingPair(BaseModel):
    name: str
    symbol: str


class Timeframe(str, Enum):
    ONE_MINUTE = "1m"
    FIVE_MINUTES = "5m"
    FIFTEEN_MINUTES = "15m"
    ONE_HOUR = "1h"
    FOUR_HOURS = "4h"
    ONE_DAY = "1d"
    ONE_WEEK = "1w"


class ExchangeOrder(BaseModel):
    timestamp: datetime
    status: OrderStatus
    trading_pair: TradingPair
    exchange_order_id: str
    side: OrderSide
    price: Decimal
    amount: Decimal
