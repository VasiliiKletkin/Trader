import inspect
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from core.utils.registry import Registry

from .schemas import PositionType

if TYPE_CHECKING:
    from exchanges.domain import Candle


class RiskManagerRegistry(Registry):
    pass


class AbstractRiskManager(ABC):
    """
    Абстрактный базовый класс для Risk Manager.
    Отвечает за контроль допустимости сделок, ограничение риска на позицию,
    расчёт уровней стоп-лосса/тейк-профита.
    """

    PARAM_CONSTRAINTS = {}

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
        position_type: PositionType,
        price: Decimal,
        balance: Decimal,
        candles: List["Candle"],
    ) -> Decimal:
        """
        Рассчитывает допустимый размер позиции на основе риска и стоп-лосса.

        :param position_type: Тип позиции (LONG/SHORT)
        :param price: Текущая цена входа
        :param balance: Доступный баланс
        :param candles: Список свечей для расчёта (например, для экстремумов)
        :return: Размер позиции (в количестве лотов или контрактов)
        """
        pass

    @abstractmethod
    def get_stop_loss(
        self,
        position_type: PositionType,
        price: Decimal,
        candles: List["Candle"],
    ) -> Optional[Decimal]:
        """
        Определяет уровень стоп-лосса для входа.

        :param position_type: Тип позиции (LONG/SHORT)
        :param price: Цена входа
        :param candles: Список свечей для расчёта (например, для экстремумов)
        :return: Цена стоп-лосса
        """
        pass

    @abstractmethod
    def get_take_profit(
        self,
        position_type: PositionType,
        price: Decimal,
        candles: List["Candle"],
    ) -> Optional[Decimal]:
        """
        Определяет уровень тейк-профита на основе risk/reward соотношения.

        :param position_type: Тип позиции (LONG/SHORT)
        :param price: Цена входа
        :param candles: Список свечей для расчёта
        :return: Цена тейк-профита
        """
        pass
