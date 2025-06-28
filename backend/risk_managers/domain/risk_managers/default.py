from decimal import Decimal
from typing import Tuple, List, Optional, Any

from strategies.domain.strategies.base import SignalType
from .base import AbstractRiskManager


class DefaultRiskManager(AbstractRiskManager):
    """
    Базовая реализация риск-менеджера,
    позволяет работать только с одной позицией
    position_size - Всегда максимальна для всего баланса
    stop_loss - Всегда равно None
    take_profit - Всегда равно None
    """

    def __init__(
        self,
        max_positions_count: int = 1,
    ):
        self.max_positions_count = max_positions_count

    def can_trade(
        self,
        signal: SignalType,
        price: Decimal,
        balance: Decimal,
        opened_positions: List[Any],
    ) -> Tuple[bool, str]:
        """
        Проверяет, можно ли открыть сделку на основе текущего состояния.

        :param signal: Торговый сигнал (например, "BUY", "SELL")
        :param price: Текущая цена актива
        :param balance: Текущий доступный баланс
        :param opened_positions: Список открытых позиций
        :return: Кортеж (можно_ли_торговать, причина_если_нельзя)
        """

        if signal not in {SignalType.BUY, SignalType.SELL}:
            return False

        if not self.check_max_positions(opened_positions):
            return False

        return True

    def calculate_position_size(
        self,
        price: Decimal,
        balance: Decimal,
    ) -> Decimal:
        """
        Вычисляет размер позиции на основе риска и расстояния до стоп-лосса.

        :param price: Цена входа
        :param balance: Текущий доступный баланс
        :return: Размер позиции
        """
        return balance / price

    def get_stop_loss(
        self,
        price: Decimal,
    ) -> Optional[Decimal]:
        """
        Вычисляет уровень стоп-лосса.

        :param price: Цена входа в сделку
        :return: Цена стоп-лосса
        """
        return None

    def get_take_profit(self, price: Decimal) -> Optional[Decimal]:
        """
        Вычисляет уровень тейк-профита.

        :param price: Цена входа
        :return: Nones
        """
        return None

    def check_max_positions(self, opened_positions: List[Any]) -> bool:
        """
        Проверяет, не превышено ли количество открытых позиций.

        :param open_positions: Список открытых позиций
        :return: True, если можно открыть ещё одну позицию, иначе False
        """
        return len(opened_positions) < self.max_positions_count
