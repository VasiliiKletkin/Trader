from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel

from exchanges.domain import ExchangeCandle


class SignalType(StrEnum):
    """Типы торговых сигналов."""

    BUY = "buy"
    SELL = "sell"
    WAIT = "wait"


class TraderSignal(BaseModel):
    """Торговый сигнал трейдера."""

    id: int | None = None
    timestamp: datetime
    price: Decimal
    candle: ExchangeCandle
    type: SignalType
    data: dict[str, Any] = {}


class ArbitrageTraderSignal(BaseModel):
    """
    Торговый сигнал арбитражного трейдера.

    Содержит свечи от двух бирж (left_candle, right_candle).
    """

    id: int | None = None
    timestamp: datetime
    left_type: SignalType
    right_type: SignalType
    left_price: Decimal
    right_price: Decimal
    left_candle: ExchangeCandle
    right_candle: ExchangeCandle | None = None
    data: dict[str, Any] = {}


class RenkoBrick(BaseModel):
    timestamp: datetime
    type: Literal["up", "down", "first"]
    open: Decimal | None
    close: Decimal | None
    low: Decimal | None = None
    high: Decimal | None = None


class RenkoState(BaseModel):
    timestamp: datetime
    bricks: list["RenkoBrick"]


class MFIState(BaseModel):
    timestamp: datetime
    mfi_value: float


class MoneyFlowIndexStrategyData(BaseModel):
    """Данные MFI сигнала."""

    mfi_value: float


class RenkoData(BaseModel):
    """Данные Renko сигнала."""

    bricks: list[RenkoBrick]


class StochasticData(BaseModel):
    k_value: float
    d_value: float | None


class DonchianCrossoverData(BaseModel):
    fast_upper: float
    fast_lower: float
    slow_upper: float
    slow_lower: float
    candle_low: float
    candle_high: float


class MovingAverageCrossoverData(BaseModel):
    fast_avg: float
    slow_avg: float


class GridTradingData(BaseModel):
    avg: float
    candle_close: float
    narrow_grid_up: float
    narrow_grid_down: float
    wide_grid_up: float
    wide_grid_down: float


class MeanReversionChannelData(BaseModel):
    """Данные стратегии Mean Reversion Channel (коридор по SMA +/- k * sigma)."""

    sma: float
    std: float
    upper: float
    lower: float
    period: int
    sigma_mult: float
    threshold: float


class SimpleArbitrageData(BaseModel):
    """Данные простой арбитражной стратегии."""

    spread: float
    price_first: float
    price_second: float
