from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel

from exchanges.domain import MarketType, TradingPair


class OrderStatus(StrEnum):
    OPENED = "opened"
    CLOSED = "closed"
    CANCELED = "canceled"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class ExchangeClientOrder(BaseModel):
    id: int | None = None
    exchange_order_id: str
    timestamp: datetime
    status: OrderStatus
    trading_pair: TradingPair
    type: OrderType
    side: OrderSide
    price: Decimal
    amount: Decimal
    fee: Decimal
    cost: Decimal


class ExchangeClientBalance(BaseModel):
    currency: str
    market_type: MarketType
    total: Decimal
    free: Decimal
    used: Decimal
    debt: Decimal
