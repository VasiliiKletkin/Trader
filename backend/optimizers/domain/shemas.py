from datetime import timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class OptimizerStatus(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    REBOOTING = "rebooting"
    ERROR = "error"


class OptimizationResult(BaseModel):
    value: float
    params: dict[str, Any]


class TraderOptimizationResult(BaseModel):
    pnl: Decimal
    win_rate: Decimal
    avg_candles_per_position: Decimal
    pnl_r2: Decimal
    roi: Decimal
    sharpe: Decimal
    total_positions: int
    strategy_arguments: dict[str, Any]
    risk_manager_arguments: dict[str, Any]
    duration: timedelta
