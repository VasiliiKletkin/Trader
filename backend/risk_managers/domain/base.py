import inspect
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Optional, TYPE_CHECKING

from .schemas import PositionType
from core.utils.registry import Registry

if TYPE_CHECKING:
    from traders.domain.traders import Trader


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
    def calculate_position_size(
        self,
        trader: "Trader",
        position_type: PositionType,
        price: Decimal,
        balance: Decimal,
    ) -> Decimal:
        """
        Рассчитывает допустимый размер позиции на основе риска и стоп-лосса.

        :param trader: Трейдер для доступа к данным свечей
        :param position_type: Тип позиции (LONG/SHORT)
        :param price: Текущая цена входа
        :param balance: Доступный баланс
        :return: Размер позиции (в количестве лотов или контрактов)
        """
        pass

    @abstractmethod
    def get_stop_loss(
        self,
        trader: "Trader",
        position_type: PositionType,
        price: Decimal,
    ) -> Optional[Decimal]:
        """
        Определяет уровень стоп-лосса для входа.

        :param trader: Трейдер для доступа к данным свечей
        :param position_type: Тип позиции (LONG/SHORT)
        :param price: Цена входа
        :return: Цена стоп-лосса
        """
        pass

    @abstractmethod
    def get_take_profit(
        self,
        trader: "Trader",
        position_type: PositionType,
        price: Decimal,
    ) -> Optional[Decimal]:
        """
        Определяет уровень тейк-профита на основе risk/reward соотношения.

        :param trader: Трейдер для доступа к данным свечей
        :param position_type: Тип позиции (LONG/SHORT)
        :param price: Цена входа
        :return: Цена тейк-профита
        """
        pass
