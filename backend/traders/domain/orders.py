from typing import Optional

from enum import Enum
from pydantic import BaseModel


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class ExchangeOrder(BaseModel):
    """
    TraderOrder represents an order placed by a trader.
    It contains the necessary information to process the order.
    """

    trader_id: str
    exchange: str
    symbol: str
    order_type: str
    side: str
    quantity: float
    price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
