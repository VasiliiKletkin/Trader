from pydantic import BaseModel


class OptimizationResult(BaseModel):
    value: float
    params: dict
