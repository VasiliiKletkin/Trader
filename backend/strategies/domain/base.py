import inspect
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from core.utils.registry import Registry
from exchanges.domain import Candle

from .schemas import ArbitrageTraderSignal, TraderSignal

if TYPE_CHECKING:
    from exchanges.domain import ExchangeCandle
    from traders.domain import (
        ArbitrageTrader,
        ArbitrageTraderPosition,
        Trader,
        TraderPosition,
    )


class StrategyRegistry(Registry):
    pass


class ArbitrageStrategyRegistry(Registry):
    pass


class AbstractStrategy(ABC):
    """
    Абстрактный базовый класс для всех торговых стратегий.

    Каждая стратегия должна реализовать методы для:
    - генерации торгового сигнала (`get_signal`)
    - сохранения/восстановления состояния (`dump_state` / `load_state`)

    Стратегии работают с базовым типом Candle и не зависят от конкретного типа свечи.
    Используются только общие свойства: open, high, low, close, volume, dt_unix.
    """

    PARAM_CONSTRAINTS: dict[str, tuple] = {}

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

        Args:
            trader: Трейдер, для которого генерируется сигнал
            candle: Свеча для анализа

        Returns:
            TraderSignal: Сигнал с типом (BUY/SELL/WAIT) и дополнительными данными
        """
        pass

    @abstractmethod
    def position_should_be_closed(
        self,
        signal: TraderSignal,
        position: "TraderPosition",
    ) -> bool:
        """
        Определяет, должны ли позиции быть закрыты на основе сигнала.

        По умолчанию возвращает True, если сигнал не WAIT.
        """
        pass


class AbstractArbitrageStrategy(ABC):
    """
    Абстрактный базовый класс для арбитражных торговых стратегий.

    Арбитражные стратегии работают с двумя биржами одновременно и генерируют
    парные сигналы (ArbitrageTraderSignal) для координированной торговли.

    Каждая арбитражная стратегия должна реализовать методы для:
    - генерации арбитражного сигнала (`get_signal`)
    - определения условий закрытия позиции (`position_should_be_closed`)
    """

    PARAM_CONSTRAINTS: dict[str, tuple] = {}

    def __init_subclass__(cls, **kwargs):
        """
        Автоматическая регистрация подклассов в `ArbitrageStrategyRegistry`,
        если они не являются абстрактными.
        """
        super().__init_subclass__(**kwargs)

        if not inspect.isabstract(cls):
            ArbitrageStrategyRegistry.register(cls)

    @abstractmethod
    def get_signal(
        self,
        trader: "ArbitrageTrader",
        first_candle: "ExchangeCandle",
        second_candle: "ExchangeCandle",
    ) -> ArbitrageTraderSignal:
        """
        Возвращает арбитражный торговый сигнал на основе данных с двух бирж.

        Args:
            trader: Арбитражный трейдер, для которого генерируется сигнал
            first_candle: Свеча с первой биржи
            second_candle: Свеча со второй биржи

        Returns:
            ArbitrageTraderSignal: Парный сигнал с типами для обеих бирж
        """
        pass

    @abstractmethod
    def position_should_be_closed(
        self,
        signal: ArbitrageTraderSignal,
        position: "ArbitrageTraderPosition",
    ) -> bool:
        """
        Определяет, должна ли арбитражная позиция быть закрыта.

        Args:
            signal: Текущий арбитражный сигнал
            position: Открытая арбитражная позиция

        Returns:
            bool: True если позицию нужно закрыть
        """
        pass
