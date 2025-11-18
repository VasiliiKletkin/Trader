from pydantic import BaseModel


class OptimizerResult(BaseModel):
    theoretical_profit: float
    strategy_arguments: dict
