import inspect
from abc import ABC, abstractmethod

from risk_managers.domain.schemas import TraderPosition
from core.utils.registry import Registry
from exchanges.domain.schemas import Candle
from .schemas import TraderSignal


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
    def get_signal(self, trader: "Trader", candle: Candle) -> TraderSignal:
        """
        Возвращает торговый сигнал на основе текущего состояния стратегии.

        Returns:
            SignalType: BUY / SELL / WAIT.
        """
        pass

    def position_should_be_closed(
        self,
        signal: TraderSignal,
        position: TraderPosition,
    ) -> bool:
        """
        Определяет, должны ли позиции быть закрыты на основе сигнала.

        По умолчанию возвращает True, если сигнал не WAIT.
        """
        pass
