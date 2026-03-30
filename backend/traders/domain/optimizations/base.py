from abc import ABC, abstractmethod
from collections.abc import Callable

from core.utils.registry import Registry

from ..schemas import OptimizationResult


class OptimizerRegistry(Registry):
    pass


class AbstractOptimizationAlgorithm(ABC):
    """ """

    @abstractmethod
    def optimize(
        self,
        score_function: Callable,
        params_constraints: dict[str, tuple[float | int, float | int]],
    ) -> OptimizationResult:
        pass
