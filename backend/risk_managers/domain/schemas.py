from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class PositionTypeDTO(str, Enum):
    LONG = "long"
    SHORT = "short"


class PositionDTO(BaseModel):
    trading_pair: str = Field(..., description="Trading pair for the position")
    type: PositionTypeDTO = Field(
        ..., description="Type of the position (long or short)"
    )
    entry_price: Decimal = Field(..., description="Entry price of the position")
    amount: Decimal = Field(..., description="Amount of the asset in the position")
    open_timestamp: datetime = Field(
        ..., description="Timestamp when the position was opened"
    )
    close_timestamp: Optional[datetime] = Field(
        None, description="Timestamp when the position was closed"
    )
    status: str = Field(..., description="Status of the position (opened or closed)")
