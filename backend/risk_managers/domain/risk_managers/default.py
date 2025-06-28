from abc import ABC
from decimal import Decimal
from typing import Tuple, List, Optional, Any
from loguru import logger
from decimal import Decimal, InvalidOperation

from risk_managers.domain.schemas import PositionType
from strategies.domain.strategies.base import SignalType
from .base import AbstractRiskManager


class PositionSizeByRiskMixin(ABC):
    """
    Миксин для расчёта размера позиции на основе допустимого риска.
    Требует, чтобы объект имел max_risk_per_trade.
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
        signal: SignalType,
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


class DefaultRiskManager(AbstractRiskManager):
    """
    Базовая реализация риск-менеджера:
    - Позволяет одну позицию на весь баланс (по умолчанию)
    - Не устанавливает stop_loss и take_profit
    - Контролирует количество позиций и максимальную просадку
    """

    def __init__(
        self,
        max_positions_count: int = 1,
        max_drawdown_pct: float = 20.0,
    ):
        """
        :param max_positions_count: Максимальное количество одновременно открытых позиций (int > 0)
        :param max_drawdown_pct: Максимальная допустимая просадка в процентах (0–100)
        """
        if not isinstance(max_positions_count, int) or max_positions_count <= 0:
            raise ValueError(
                "max_positions_count должен быть положительным целым числом"
            )

        if not (0 <= max_drawdown_pct <= 100):
            raise ValueError("max_drawdown_pct должен быть в диапазоне от 0 до 100")

        self.max_positions_count = max_positions_count
        self.max_drawdown_pct = max_drawdown_pct
        logger.debug(
            f"[RiskManager] Инициализирован с {max_positions_count=}, {max_drawdown_pct=}%"
        )

    def can_trade(
        self,
        signal: SignalType,
        price: Decimal,
        balance: Decimal,
        opened_positions: List[Any],
        initial_balance: Decimal,
    ) -> bool:
        """
        Проверяет, можно ли открыть сделку на основе текущего сигнала, баланса и позиций.

        :return: True/False
        """
        if signal not in {SignalType.BUY, SignalType.SELL}:
            return False

        if not self.check_drawdown_limit(balance, initial_balance):
            return False

        if not self.check_max_positions(opened_positions):
            return False

        return True

    def get_stop_loss(
        self,
        signal: SignalType,
        price: Decimal,
    ) -> Optional[Decimal]:
        """По умолчанию стоп-лосс не устанавливается"""
        return None

    def get_take_profit(
        self,
        signal: SignalType,
        price: Decimal,
    ) -> Optional[Decimal]:
        """По умолчанию тейк-профит не устанавливается"""
        return None

    def get_position_type(self, signal: SignalType) -> Optional[str]:
        """
        Возвращает тип позиции на основе сигнала.

        :param signal: BUY / SELL
        :return: PositionType.LONG или SHORT
        """
        if signal == SignalType.BUY:
            return PositionType.LONG
        elif signal == SignalType.SELL:
            return PositionType.SHORT
        return None

    def get_percent(self, price: Decimal, new_price: Decimal) -> Decimal:
        """
        Возвращает процентное изменение от price до new_price.
        Пример: (105 - 100) / 100 * 100 = 5.0 (%)

        :return: Decimal с округлением до 2 знаков
        """
        try:
            if price == 0:
                return Decimal("0.0")

            change = ((new_price - price) / price) * Decimal("100")
            return change.quantize(Decimal("0.01"))
        except (InvalidOperation, ZeroDivisionError):
            return Decimal("0.0")

    def check_max_positions(self, opened_positions: List[Any]) -> bool:
        """
        Проверяет, можно ли открыть ещё одну позицию.

        :return: True, если меньше лимита
        """
        return len(opened_positions) < self.max_positions_count

    def check_drawdown_limit(self, balance: Decimal, initial_balance: Decimal) -> bool:
        """
        Проверяет, не превышена ли просадка от начального баланса.

        :return: True, если просадка допустима
        """
        try:
            allowed_min_balance = initial_balance * (
                1 - Decimal(self.max_drawdown_pct) / Decimal("100")
            )
            return balance >= allowed_min_balance
        except (InvalidOperation, TypeError):
            return False
