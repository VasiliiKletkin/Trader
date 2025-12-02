from pydantic import BaseModel


class OptimizationResult(BaseModel):
    theoretical_profit: float
    risk_manager_arguments: dict
    strategy_arguments: dict
