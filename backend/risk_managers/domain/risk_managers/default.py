from typing import Tuple, List, Optional, Any

from backend.strategies.domain.strategies.base import SignalType
from .base import AbstractRiskManager


class DefaultRiskManager(AbstractRiskManager):
    """
    Базовая реализация риск-менеджера, контролирующая риск на сделку, просадку и количество позиций.
    """

    def __init__(
        self,
        initial_balance: Optional[float] = None,
        max_risk_per_trade: float = 0.01,
        max_drawdown: float = 0.2,
        max_positions: int = 1,
    ):
        """
        :param max_risk_per_trade: Максимальный риск на одну сделку (доля от баланса, например, 0.01 = 1%)
        :param max_drawdown: Максимально допустимая просадка от начального баланса (например, 0.2 = 20%)
        :param max_positions: Максимальное количество одновременно открытых позиций
        :param initial_balance: Начальный баланс (если не указан, будет установлен при первом вызове)
        """
        self.max_risk_per_trade = max_risk_per_trade
        self.max_drawdown = max_drawdown
        self.max_positions = max_positions
        self.initial_balance = initial_balance

    def can_trade(
        self, signal: str, price: float, balance: float, opened_positions: List[Any]
    ) -> Tuple[bool, str]:
        """
        Проверяет, можно ли открыть сделку на основе текущего состояния.

        :param signal: Торговый сигнал (например, "BUY", "SELL")
        :param price: Текущая цена актива
        :param balance: Текущий доступный баланс
        :param opened_positions: Список открытых позиций
        :return: Кортеж (можно_ли_торговать, причина_если_нельзя)
        """

        if signal not in (SignalType.BUY, SignalType.SELL):
            return False

        if not self.check_drawdown_limit(balance):
            return False

        if not self.check_max_positions(opened_positions):
            return False

        return True

    def calculate_position_size(
        self, price: float, stop_loss: float, balance: float
    ) -> float:
        """
        Вычисляет размер позиции на основе риска и расстояния до стоп-лосса.

        :param price: Цена входа
        :param stop_loss: Цена стоп-лосса
        :param balance: Текущий доступный баланс
        :return: Размер позиции (в контрактах/лотах/единицах)
        """
        stop_distance = abs(price - stop_loss)
        if stop_distance == 0:
            return 0.0

        risk_amount = balance * self.max_risk_per_trade
        position_size = risk_amount / stop_distance

        return round(position_size, 4)

    def get_stop_loss(
        self,
        price: float,
        volatility: Optional[float] = None,
        risk_percent: float = 1.0,
    ) -> float:
        """
        Вычисляет уровень стоп-лосса для входа.

        :param price: Цена входа в сделку
        :param volatility: (необязательно) Значение волатильности, если задано, используется для расчёта стоп-лосса
        :param risk_percent: Процент допустимого риска от входной цены, используется если волатильность не указана (по умолчанию 1.0%)
        :return: Цена стоп-лосса
        """
        if volatility:
            return price - volatility
        return price * (1 - risk_percent / 100)

    def get_take_profit(self, entry_price: float, rr_ratio: float = 2.0) -> float:
        """
        Вычисляет уровень тейк-профита по заданному RR-отношению.

        :param entry_price: Цена входа
        :param rr_ratio: Соотношение риск/прибыль (например, 2.0 = риск 1%, прибыль 2%)
        :return: Цена тейк-профита
        """
        stop_loss = self.get_stop_loss(entry_price)
        stop_size = abs(entry_price - stop_loss)
        return entry_price + stop_size * rr_ratio

    def check_drawdown_limit(self, balance: float) -> bool:
        """
        Проверяет, не превышена ли просадка от начального баланса.

        :param balance: Текущий баланс
        :return: True, если просадка в допустимых пределах, иначе False
        """
        if self.initial_balance is None:
            return True

        drawdown = (self.initial_balance - balance) / self.initial_balance
        return drawdown <= self.max_drawdown

    def check_max_positions(self, open_positions: List[Any]) -> bool:
        """
        Проверяет, не превышено ли количество открытых позиций.

        :param open_positions: Список открытых позиций
        :return: True, если можно открыть ещё одну позицию, иначе False
        """
        return len(open_positions) < self.max_positions
