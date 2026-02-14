import inspect
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from core.utils.registry import Registry

from ..schemas import ArbitrageTraderSignal

if TYPE_CHECKING:
    from arbitrage_traders.domain.schemas import ArbitrageTraderPosition
    from arbitrage_traders.domain.traders import ArbitrageTrader
    from exchanges.domain import ExchangeCandle


class ArbitrageStrategyRegistry(Registry):
    pass


class AbstractArbitrageStrategy(ABC):
    """
    Абстрактный базовый класс для арбитражных торговых стратегий.

    Арбитражные стратегии работают с двумя биржами одновременно и генерируют
    парные сигналы (ArbitrageTraderSignal) для координированной торговли.
    """

    PARAM_CONSTRAINTS: dict[str, tuple] = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not inspect.isabstract(cls):
            ArbitrageStrategyRegistry.register(cls)

    @abstractmethod
    def get_signal(
        self,
        trader: "ArbitrageTrader",
        left_candle: "ExchangeCandle",
        right_candle: "ExchangeCandle",
    ) -> ArbitrageTraderSignal:
        pass

    @abstractmethod
    def position_should_be_closed(
        self,
        signal: ArbitrageTraderSignal,
        position: "ArbitrageTraderPosition",
    ) -> bool:
        pass
