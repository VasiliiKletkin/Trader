from datetime import datetime
from enum import Enum

from decimal import Decimal
from pydantic import BaseModel

from exchanges.domain import TradingPair


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


class ExchangeClientOrder(BaseModel):
    timestamp: datetime
    status: OrderStatus
    trading_pair: TradingPair
    exchange_order_id: str
    type: OrderType
    side: OrderSide
    price: Decimal
    amount: Decimal
    fee: Decimal
    cost: Decimal


class ExchangeClientBalance(BaseModel):
    currency: str
    total: Decimal
    free: Decimal
    used: Decimal
    debt: Decimal
