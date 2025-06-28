from decimal import Decimal
from typing import Tuple, List, Optional, Any

from strategies.domain.strategies.base import SignalType
from .base import AbstractRiskManager


class RenkoRiskManager(DefaultRiskManager):
    """
    RenkoRiskManager риск-менеджера:
    """

    def __init__(
        self,
        max_risk_per_trade: float = 0.01,
        max_drawdown_pct: float = 0.2,
    ):
        """
        :param initial_balance: Начальный баланс (если не указан, будет установлен при первом вызове)
        :param max_risk_per_trade: Максимальный риск на одну сделку (доля от баланса, например, 0.01 = 1%)
        :param max_drawdown_pct: Максимально допустимая просадка от начального баланса (например, 0.2 = 20%)
        :param max_positions_count: Максимальное количество одновременно открытых позиций
        """
        self.max_risk_per_trade = max_risk_per_trade
        self.max_drawdown_pct = max_drawdown_pct
        self.max_positions_count = 1

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

        if signal not in (SignalType.BUY, SignalType.SELL):
            return False

        if not self.check_drawdown_limit(balance):
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
        Вычисляет уровень стоп-лосса для входа.

        :param price: Цена входа в сделку
        :return: Цена стоп-лосса
        """
        trashold_up = 1.0
        trashold_down = 1.0

        if position_type == "long":
            return 100 - 2 * trashold_down
        else:
            return 100 + 2 * trashold_up

        # так же может быть вариант без stop_loss

        2 * АТР или 1.5 * ATR

    def get_take_profit(self, price: Decimal,) -> Optional[Decimal]:

        """
        Вычисляет уровень тейк-профита по заданному RR-отношению.

        :param price: Цена входа
        :return: Цена тейк-профита
        """

        return 2 * self.get_stop_loss(price=price, position_type=position_type)
        #or None тут можно так же None

    def check_drawdown_limit(self, balance: Decimal) -> bool:
        """
        Проверяет, не превышена ли просадка от начального баланса.

        :param balance: Текущий баланс
        :return: True, если просадка в допустимых пределах, иначе False
        """
        if self.initial_balance is None:
            return True
        min_allowed_balance = self.initial_balance * (1 - self.max_drawdown_pct)
        return balance >= min_allowed_balance

    def check_max_positions(self, opened_positions: List[Any]) -> bool:
        """
        Проверяет, не превышено ли количество открытых позиций.

        :param open_positions: Список открытых позиций
        :return: True, если можно открыть ещё одну позицию, иначе False
        """
        return len(opened_positions) < self.max_positions_count




class DefaultRiskManager(AbstractRiskManager):
    """
    Базовая реализация риск-менеджера, контролирующая риск на сделку, просадку и количество позиций.
    """

    def __init__(
        self,
        initial_balance: Optional[float] = 100,
        max_risk_per_trade: float = 0.01,
        max_drawdown_pct: float = 0.2,
        max_positions_count: int = 1,
    ):
        """
        :param initial_balance: Начальный баланс (если не указан, будет установлен при первом вызове)
        :param max_risk_per_trade: Максимальный риск на одну сделку (доля от баланса, например, 0.01 = 1%)
        :param max_drawdown_pct: Максимально допустимая просадка от начального баланса (например, 0.2 = 20%)
        :param max_positions_count: Максимальное количество одновременно открытых позиций
        """
        self.initial_balance = initial_balance
        self.max_risk_per_trade = max_risk_per_trade
        self.max_drawdown_pct = max_drawdown_pct
        self.max_positions_count = max_positions_count

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

    def calculate_position_size(self, price: float, balance: float) -> float:
        """
        Вычисляет размер позиции на основе риска и расстояния до стоп-лосса.

        :param price: Цена входа
        :param balance: Текущий доступный баланс
        :return: Размер позиции (в контрактах/лотах/единицах)
        """
        stop_loss = self.get_stop_loss(price)
        stop_distance = abs(price - stop_loss)
        if stop_distance == 0:
            return 0.0

        risk_amount = balance * self.max_risk_per_trade
        position_size = risk_amount / stop_distance

        return round(position_size, 4)

    def get_stop_loss(
        self,
        price: float,
    ) -> float:
        """
        Вычисляет уровень стоп-лосса для входа.

        :param price: Цена входа в сделку
        :return: Цена стоп-лосса
        """
        percentage_stop_loss = 0.1  # Пример: стоп-лосс на 10% ниже цены входа
        return price - (price * percentage_stop_loss)

    def get_take_profit(self, price: float) -> float:
        """
        Вычисляет уровень тейк-профита по заданному RR-отношению.

        :param price: Цена входа
        :return: Цена тейк-профита
        """
        return price + (price * 0.02)

    def check_drawdown_limit(self, balance: float) -> bool:
        """
        Проверяет, не превышена ли просадка от начального баланса.

        :param balance: Текущий баланс
        :return: True, если просадка в допустимых пределах, иначе False
        """
        if self.initial_balance is None:
            return True
        min_allowed_balance = float(self.initial_balance) * (1 - self.max_drawdown_pct)
        return balance >= min_allowed_balance

    def check_max_positions(self, opened_positions: List[Any]) -> bool:
        """
        Проверяет, не превышено ли количество открытых позиций.

        :param open_positions: Список открытых позиций
        :return: True, если можно открыть ещё одну позицию, иначе False
        """
        return len(opened_positions) < self.max_positions_count
