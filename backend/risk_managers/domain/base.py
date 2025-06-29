from abc import ABC, abstractmethod
from decimal import Decimal
import inspect
from typing import Optional, List, Any

from strategies.domain.schemas import SignalType
from core.utils.registry import Registry


class RiskManagerRegistry(Registry):
    pass


class AbstractRiskManager(ABC):
    """
    Абстрактный базовый класс для Risk Manager.
    Отвечает за контроль допустимости сделок, ограничение риска на позицию,
    расчёт уровней стоп-лосса/тейк-профита и контроль просадки.
    """

    def __init_subclass__(cls, **kwargs):
        """
        Автоматическая регистрация подклассов в `RiskManagerRegistry`,
        если они не являются абстрактными.
        """
        super().__init_subclass__(**kwargs)

        if not inspect.isabstract(cls):
            RiskManagerRegistry.register(cls)

    @abstractmethod
    def can_trade(
        self,
        signal: SignalType,
        price: Decimal,
        balance: Decimal,
        opened_positions: List[Any],
        initial_balance: Decimal,
    ) -> bool:
        """
        Проверяет, можно ли открыть сделку на основе сигнала, текущего баланса и открытых позиций.

        :param signal: Торговый сигнал ('BUY', 'SELL', и т.д.)
        :param price: Текущая цена актива
        :param balance: Доступный баланс
        :param opened_positions: Список открытых позиций
        :return: разрешено ли открыть сделку
        """
        pass

    @abstractmethod
    def calculate_position_size(
        self,
        signal: SignalType,
        price: Decimal,
        balance: Decimal,
    ) -> Decimal:
        """
        Рассчитывает допустимый размер позиции на основе риска и стоп-лосса.

        :param price: Текущая цена входа
        :param stop_loss: Уровень стоп-лосса
        :param balance: Доступный баланс
        :return: Размер позиции (в количестве лотов или контрактов)
        """
        pass

    @abstractmethod
    def get_stop_loss(
        self,
        signal: SignalType,
        price: Decimal,
    ) -> Optional[Decimal]:
        """
        Определяет уровень стоп-лосса для входа.

        :param price: Цена входа
        :return: Цена стоп-лосса
        """
        pass

    @abstractmethod
    def get_take_profit(
        self,
        signal: SignalType,
        price: Decimal,
    ) -> Optional[Decimal]:
        """
        Определяет уровень тейк-профита на основе risk/reward соотношения.

        :param price: Цена входа
        :return: Цена тейк-профита
        """
        pass

    @abstractmethod
    def load_data(self, data: dict[str, Any]) -> None:
        """
        Загружает данные риск-менеджера из словаря.

        :param data: Словарь с данными
        """
        pass
    @abstractmethod
    def dump_data(self) -> dict[str, Any]:
        """
        Сериализует состояние риск-менеджера в словарь.

        :return: Словарь с данными
        """
        data = {}
        return data
        pass
