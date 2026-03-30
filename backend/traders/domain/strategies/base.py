from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from core.utils.registry import Registry
from exchanges.domain import ExchangeCandle

from ..schemas import TraderSignal

if TYPE_CHECKING:
    from ..schemas import TraderPosition
    from ..traders.traders import Trader


class StrategyRegistry(Registry):
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

    @abstractmethod
    def get_signal(self, trader: "Trader", candle: ExchangeCandle) -> TraderSignal:
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
