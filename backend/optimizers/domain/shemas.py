from typing import Any, Dict
from pydantic import BaseModel


class OptimizationResult(BaseModel):
    value: float
    params: Dict[str, Any]


class TraderOptimizationResult(OptimizationResult):
    theoretical_profit: float
    strategy_arguments: Dict[str, Any]
    risk_manager_arguments: Dict[str, Any]
