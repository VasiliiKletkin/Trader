import datetime
from typing import Literal, Optional, Union
from pydantic import BaseModel, Field


class Brick(BaseModel):
    """
    Модель для описания одного кирпичика Renko.
    """

    timestamp: Optional[Union[datetime, float]] = Field(
        default=None,
        description="Временная метка, связанная с кирпичиком (например, дата или UNIX-время)",
    )
    type: Literal["up", "down", "first"] = Field(
        ...,
        description="Тип кирпичика: 'up', 'down' или 'first'",
    )
    open: Optional[float] = Field(
        default=None,
        description="Цена открытия кирпичика",
    )
    close: Optional[float] = Field(
        default=None,
        description="Цена закрытия кирпичика",
    )
    low: Optional[float] = Field(
        default=None,
        description="Минимальная цена тени (вниз), если есть",
    )
    high: Optional[float] = Field(
        default=None,
        description="Максимальная цена тени (вверх), если есть",
    )
