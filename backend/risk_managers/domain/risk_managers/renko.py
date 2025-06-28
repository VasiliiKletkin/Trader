from decimal import Decimal, InvalidOperation
from typing import Optional
from loguru import logger

from risk_managers.domain.schemas import PositionType
from strategies.domain.strategies.base import SignalType
from .default import DefaultRiskManager


class RenkoDefaultRiskManager(DefaultRiskManager):
    """
    Риск-менеджер для Renko-стратегии.

    Особенности:
    - stop_loss рассчитывается на основе процентных порогов `trashold_up` и `trashold_down`.
    - take_profit рассчитывается через RR-отношение (`risk/reward`).
    """

    def __init__(
        self,
        max_positions_count: int = 1,
        max_drawdown_pct: float = 20.0,
        trashold_up: float = 1.0,
        trashold_down: float = 1.0,
        rr_ratio: float = 2.0,
    ):
        super().__init__(
            max_positions_count=max_positions_count,
            max_drawdown_pct=max_drawdown_pct,
        )
        self.trashold_up = trashold_up
        self.trashold_down = trashold_down
        self.rr_ratio = rr_ratio

    def get_stop_loss(
        self,
        signal: SignalType,
        price: Decimal,
    ) -> Optional[Decimal]:
        """
        Вычисляет уровень стоп-лосса на основе направления позиции и заданных порогов.

        :param signal: Торговый сигнал (BUY / SELL)
        :param price: Цена входа
        :return: Цена стоп-лосса или None
        """
        try:
            position_type = self.get_position_type(signal)
            if position_type == PositionType.LONG:
                stop_loss = price - (
                    price * Decimal(self.trashold_down) / Decimal("100")
                )
            elif position_type == PositionType.SHORT:
                stop_loss = price + (price * Decimal(self.trashold_up) / Decimal("100"))
            else:
                logger.warning("Неизвестный тип позиции: {}", position_type)
                return None

            logger.debug(f"[Risk] Стоп-лосс для {position_type}: {stop_loss:.4f}")
            return stop_loss

        except (InvalidOperation, TypeError) as e:
            logger.error(f"Ошибка расчета stop_loss: {e}")
            return None

    def get_take_profit(
        self,
        signal: SignalType,
        price: Decimal,
    ) -> Optional[Decimal]:
        """
        Вычисляет уровень тейк-профита на основе RR-отношения (reward-to-risk).

        :param signal: Торговый сигнал (BUY / SELL)
        :param price: Цена входа
        :return: Цена тейк-профита или None
        """
        try:
            stop_loss = self.get_stop_loss(price=price, signal=signal)
            if stop_loss is None or price is None or not self.rr_ratio:
                logger.warning("Недостаточно данных для расчета тейк-профита.")
                return None

            position_type = self.get_position_type(signal)
            risk_distance = abs(price - stop_loss)
            reward_distance = risk_distance * Decimal(self.rr_ratio)

            if position_type == PositionType.LONG:
                take_profit = price + reward_distance
            elif position_type == PositionType.SHORT:
                take_profit = price - reward_distance
            else:
                logger.warning("Неизвестный тип позиции при расчёте тейк-профита.")
                return None

            logger.debug(
                f"[Risk] Take-profit для {position_type}: {take_profit:.4f} "
                f"(risk: {risk_distance:.4f}, rr: {self.rr_ratio})"
            )
            return take_profit

        except (InvalidOperation, TypeError) as e:
            logger.error(f"Ошибка расчета take_profit: {e}")
            return None
