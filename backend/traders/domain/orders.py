from decimal import Decimal
from enum import Enum
from pydantic import BaseModel

from exchanges.domain.schemas import TradingPair


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class ExchangeOrder(BaseModel):
    side: OrderSide
    trading_pair: TradingPair
    price: Decimal
    amount: Decimal
