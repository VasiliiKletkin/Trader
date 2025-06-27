from typing import Tuple, List, Optional, Any

from strategies.domain.strategies.base import SignalType
from .base import AbstractRiskManager


take дщыы 
это минимальное значение за несколько свечей 


class MFIRiskManager(AbstractRiskManager):
    """
    RenkoRiskManager риск-менеджера, контролирующая риск на сделку, просадку и количество позиций.
    """

    def __init__(
        self,
        initial_balance: Optional[float] = 100,
        max_risk_per_trade: float = 0.01,
        max_drawdown_pct: float = 0.2,
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
        self.max_positions_count = 1

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
        return balance

    def get_stop_loss(self, position_type: str, price: float) -> float:
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

    def get_take_profit(self, position_type, price: float) -> float:
        """
        Вычисляет уровень тейк-профита по заданному RR-отношению.

        :param entry_price: Цена входа
        :return: Цена тейк-профита
        """

        return 2 * self.get_stop_loss(price=price, position_type=position_type)
        #or None тут можно так же None

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
