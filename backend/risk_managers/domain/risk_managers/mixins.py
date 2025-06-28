from abc import ABC
from decimal import Decimal
from typing import Tuple, List, Optional, Any

from strategies.domain.strategies.base import SignalType


class PositionSizeByRiskMixin(ABC):
    """
    Миксин для расчёта размера позиции на основе допустимого риска.
    Требует, чтобы объект имел max_risk_per_trade и метод get_stop_loss(price).
    """

    max_risk_per_trade: float

    def calculate_position_size(
        self,
        price: Decimal,
        balance: Decimal,
    ) -> Decimal:
        """
        Расчёт размера позиции по допущенному риску и расстоянию до стопа.

        :param price: Цена входа
        :param balance: Баланс трейдера
        :return: Размер позиции
        """
        stop_loss = self.get_stop_loss(price)
        stop_distance = abs(price - stop_loss)
        if stop_distance == 0:
            return 0.0

        risk_amount = balance * self.max_risk_per_trade
        position_size = risk_amount / stop_distance

        return position_size


class PositionSizeAvailableBalanceMixin(ABC):
    def calculate_position_size(
        self,
        price: Decimal,
        balance: Decimal,
    ) -> Decimal:
        """
        Вычисляет размер позиции на основе доступного баланса

        :param price: Цена входа
        :param balance: Текущий доступный баланс
        :return: Размер позиции
        """
        return balance / price
