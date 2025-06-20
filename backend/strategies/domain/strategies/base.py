import inspect
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict

from core.utils.registry import Registry
from exchanges.domain.schemas import CandleDTO


class SignalType(str, Enum):
    BUY = "buy"
    SELL = "sell"
    WAIT = "wait"


class StrategyRegistry(Registry):
    pass


class AbstractStrategy(ABC):
    """
    Абстрактный базовый класс для всех торговых стратегий.

    Каждая стратегия должна реализовать методы для:
    - обработки новых свечей (`handle_candle`)
    - генерации торгового сигнала (`get_signal`)
    - сохранения/восстановления состояния (`dump_data` / `load_data`)
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
    def handle_candle(self, candle: CandleDTO) -> None:
        """
        Обработка новой поступившей свечи.

        Args:
            candle (CandleDTO): Свеча, содержащая OHLCV и временную метку.
        """
        pass

    @abstractmethod
    def get_signal(self) -> SignalType:
        """
        Возвращает торговый сигнал на основе текущего состояния стратегии.

        Returns:
            SignalType: BUY / SELL / HOLD (в зависимости от стратегии).
        """
        pass

    @abstractmethod
    def load_data(self, data: Dict[str, Any]) -> None:
        """
        Загружает сохранённое состояние стратегии (для восстановления после перезапуска).

        Args:
            data (Dict[str, Any]): Словарь с данными, ранее возвращёнными методом `dump_data`.
        """
        pass

    @abstractmethod
    def dump_data(self) -> Dict[str, Any]:
        """
        Сохраняет текущее состояние стратегии для возможности восстановления в будущем.

        Returns:
            Dict[str, Any]: Словарь, содержащий сериализованное состояние стратегии.
        """
        pass
