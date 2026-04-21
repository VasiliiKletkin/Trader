from abc import ABC, abstractmethod
from decimal import Decimal
from typing import TYPE_CHECKING

from core.utils.registry import Registry

from ..schemas import PositionType

if TYPE_CHECKING:
    from ..traders.traders import Trader


class RiskManagerRegistry(Registry):
    pass


class AbstractRiskManager(ABC):
    """
    Абстрактный базовый класс для Risk Manager.
    Отвечает за контроль допустимости сделок, ограничение риска на позицию,
    расчёт уровней стоп-лосса/тейк-профита и контроль просадки.
    """

    PARAM_CONSTRAINTS: dict[str, tuple[float, float]] = {}

    @abstractmethod
    def calculate_position_size(
        self,
        trader: "Trader",
        position_type: PositionType,
        price: Decimal,
        balance: Decimal,
    ) -> Decimal:
        """
        Рассчитывает размер позиции как cost в валюте расчёта (settle_currency).

        Возвращает cost, а не amount: единая размерность независимо от
        типа контракта (spot/linear/inverse). Преобразование cost → amount
        выполняется в Trader через trading_pair.cost_to_amount().

        :param trader: Трейдер для доступа к данным свечей
        :param position_type: Тип позиции (LONG/SHORT)
        :param price: Текущая цена входа
        :param balance: Доступный баланс (в settle_currency)
        :return: cost позиции в settle_currency
        """
        pass

    @abstractmethod
    def get_stop_loss(
        self,
        trader: "Trader",
        position_type: PositionType,
        price: Decimal,
    ) -> Decimal | None:
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
    ) -> Decimal | None:
        """
        Определяет уровень тейк-профита на основе risk/reward соотношения.

        :param trader: Трейдер для доступа к данным свечей
        :param position_type: Тип позиции (LONG/SHORT)
        :param price: Цена входа
        :return: Цена тейк-профита
        """
        pass
