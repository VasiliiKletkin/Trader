from abc import ABC, abstractmethod
import inspect
from typing import Tuple, Optional, List, Any

from strategies.domain.strategies.base import SignalType
from core.utils.registry import Registry


class PositionManagerRegistry(Registry):
    pass


class AbstractPositionManager(ABC):
    """
    Абстрактный базовый класс для менеджера позиций.
    Отвечает за контроль допустимости сделок, ограничение риска на позицию,
    расчёт уровней стоп-лосса/тейк-профита и контроль просадки.
    """

    def __init_subclass__(cls, **kwargs):
        """
        Автоматическая регистрация подклассов в `PositionManagerRegistry`,
        если они не являются абстрактными.
        """
        super().__init_subclass__(**kwargs)

        if not inspect.isabstract(cls):
            PositionManagerRegistry.register(cls)
