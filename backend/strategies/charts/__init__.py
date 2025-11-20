from .renko import app as RenkoStrategyChart
from .mfi import app as MoneyFlowIndexStrategy
from .stochastic import app as StochasticStrategyChart
from .donchian_crossover import app as DonchianCrossoverStrategy
from .moving_average_crossover import app as MovingAverageCrossoverChart


__all__ = [
    "RenkoStrategyChart",
    "MoneyFlowIndexStrategy",
    "StochasticStrategyChart",
    "DonchianCrossoverStrategy",
    "MovingAverageCrossoverChart",  
]