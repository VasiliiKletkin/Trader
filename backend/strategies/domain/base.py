import inspect
from abc import ABC, abstractmethod
from typing import Any, Dict, List

from core.utils.registry import Registry
from exchanges.domain.schemas import Candle

from .schemas import SignalType


class StrategyRegistry(Registry):
    pass


class AbstractStrategy(ABC):
    """
    Абстрактный базовый класс для всех торговых стратегий.

    Каждая стратегия должна реализовать методы для:
    - генерации торгового сигнала (`get_signal`)
    - сохранения/восстановления состояния (`dump_state` / `load_state`)
    """

    def __init_subclass__(cls, **kwargs):
        """
        Автоматическая регистрация подклассов в `StrategyRegistry`,
        если они не являются абстрактными.
        """
        super().__init_subclass__(**kwargs)

        if not inspect.isabstract(cls):
            StrategyRegistry.register(cls)

    @abstractmethod
    def get_signal(self, candle: Candle) -> SignalType:
        """
        Возвращает торговый сигнал на основе текущего состояния стратегии.

        Returns:
            SignalType: BUY / SELL / WAIT.
        """
        pass

    @abstractmethod
    def load_state(self, data: Dict[str, Any]) -> None:
        """
        Загружает сохранённое состояние стратегии (для восстановления после перезапуска).

        Args:
            data (Dict[str, Any]): Словарь с данными, ранее возвращёнными методом `dump_state`.
        """
        pass

    @abstractmethod
    def dump_state(self) -> Dict[str, Any]:
        """
        Сохраняет текущее состояние стратегии для возможности восстановления в будущем.

        Returns:
            Dict[str, Any]: Словарь, содержащий сериализованное состояние стратегии.
        """
        pass
