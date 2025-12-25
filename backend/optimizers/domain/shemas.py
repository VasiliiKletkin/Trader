from datetime import timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Dict
from pydantic import BaseModel


class OptimizerStatus(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    REBOOTING = "rebooting"
    ERROR = "error"


class OptimizationResult(BaseModel):
    value: float
    params: Dict[str, Any]


class TraderOptimizationResult(BaseModel):
    pnl: Decimal
    win_rate: Decimal
    avg_candles_per_position: Decimal
    pnl_r2: Decimal
    roi: Decimal
    sharpe: Decimal
    total_positions: int
    strategy_arguments: Dict[str, Any]
    risk_manager_arguments: Dict[str, Any]
    duration: timedelta
