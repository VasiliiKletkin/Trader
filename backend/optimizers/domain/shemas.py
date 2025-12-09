from typing import Any, Dict
from pydantic import BaseModel


class OptimizationResult(BaseModel):
    value: float
    params: Dict[str, Any]


class TraderOptimizationResult(BaseModel):
    pnl: float
    win_rate: float
    avg_candles_per_position: float
    pnl_r2: float
    roi: float
    sharpe: float
    total_positions: int
    avg_pnl_per_position: float
    strategy_arguments: Dict[str, Any]
    risk_manager_arguments: Dict[str, Any]
