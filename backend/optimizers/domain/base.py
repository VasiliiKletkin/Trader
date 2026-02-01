import inspect
from abc import ABC, abstractmethod
from typing import Callable

from core.utils.registry import Registry

from .shemas import OptimizationResult


class OptimizerRegistry(Registry):
    pass


class AbstractOptimizationAlgorithm(ABC):
    """ """

    def __init_subclass__(cls, **kwargs):
        """
        Автоматическая регистрация подклассов в `OptimizerRegistry`,
        если они не являются абстрактными.
        """
        super().__init_subclass__(**kwargs)

        if not inspect.isabstract(cls):
            OptimizerRegistry.register(cls)

    @abstractmethod
    def optimize(
        self,
        score_function: Callable,
        argument_ranges: dict,
    ) -> OptimizationResult:
        pass
