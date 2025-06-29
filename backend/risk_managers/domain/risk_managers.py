from decimal import Decimal, DivisionByZero, InvalidOperation
from typing import Any, List, Optional

from loguru import logger
import pandas as pd

from backend.exchanges.domain.schemas import CandleDTO

from .base import AbstractRiskManager, SignalType
from .schemas import PositionType


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

    def calculate_position_size(
        self,
        signal: SignalType,
        price: Decimal,
        balance: Decimal,
    ) -> Decimal:
        """
        Расчёт позиции: весь доступный баланс по текущей цене.

        :return: Размер позиции (контракты, лоты и т.п.)
        """
        try:
            return balance / price
        except DivisionByZero:
            logger.error(
                f"[RiskManager] Деление на ноль при расчёте позиции: price={price}"
            )
            return Decimal("0.0")

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
                1 - Decimal(str(self.max_drawdown_pct)) / Decimal("100")
            )
            return balance >= allowed_min_balance
        except (InvalidOperation, TypeError):
            return False

    def load_data(self, data: dict[str, Any]) -> None:
        """
        Загружает данные риск-менеджера из словаря.

        :param data: Словарь с данными
        """
        logger.debug(f"[RiskManager] Данные загружены: {data}")

    def dump_data(self) -> dict[str, Any]:
        """
        Сериализует состояние риск-менеджера в словарь.

        :return: Словарь с данными
        """
        data = {}
        logger.debug(f"[RiskManager] Данные сериализованы: {data}")
        return data


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
                    price * Decimal(str(self.trashold_down)) / Decimal("100")
                )
            elif position_type == PositionType.SHORT:
                stop_loss = price + (
                    price * Decimal(str(self.trashold_up)) / Decimal("100")
                )
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
            reward_distance = risk_distance * Decimal(str(self.rr_ratio))

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

    def load_data(self, data: dict[str, Any]) -> None:
        """
        Загружает данные риск-менеджера из словаря.

        :param data: Словарь с данными
        """
        logger.debug(f"[RiskManager] Данные загружены: {data}")

    def dump_data(self) -> dict[str, Any]:
        """
        Сериализует состояние риск-менеджера в словарь.

        :return: Словарь с данными
        """
        data = {}
        logger.debug(f"[RiskManager] Данные сериализованы: {data}")
        return data


class RiskManagerPositionSizeByRisk(DefaultRiskManager):
    """
    Риск-менеджер, рассчитывающий размер позиции на основе допустимого риска в процентах от баланса.

    Пример:
        max_risk_per_trade = 1.5 → риск не более 1.5% от баланса на одну сделку.
    """

    def __init__(
        self,
        max_positions_count: int = 1,
        max_drawdown_pct: float = 20.0,
        max_risk_per_trade: float = 1.5,
    ):
        """
        :param max_risk_per_trade: Допустимый риск в % от баланса на одну сделку (0 < X <= 100)
        """
        super().__init__(
            max_positions_count=max_positions_count,
            max_drawdown_pct=max_drawdown_pct,
        )
        if not (0 < max_risk_per_trade <= 100):
            raise ValueError(
                "max_risk_per_trade должен быть в диапазоне (0, 100] — в процентах"
            )

        self.max_risk_per_trade = Decimal(str(max_risk_per_trade))
        self.candles: List[CandleDTO] = []
        logger.debug(
            f"[RiskManager] Риск на сделку установлен: {self.max_risk_per_trade}%"
        )

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
        position_type = self.get_position_type(signal)
        df_candles = pd.DataFrame(
            [c.model_dump(exclude="dt_unix") for c in self.candles[-5:]]
        )
        if position_type == PositionType.LONG:
            stop_loss = df_candles["low"].min()
        elif position_type == PositionType.SHORT:
            stop_loss = df_candles["high"].max()
        else:
            logger.warning("Неизвестный тип позиции: {}", position_type)
            return None

        logger.debug(f"[Risk] Стоп-лосс для {position_type}: {stop_loss:.4f}")
        return stop_loss

    def calculate_position_size(
        self,
        signal: SignalType,
        price: Decimal,
        balance: Decimal,
    ) -> Decimal:
        """
        Расчёт размера позиции на основе риска и расстояния до стоп-лосса.

        :param signal: BUY / SELL
        :param price: Цена входа
        :param balance: Баланс трейдера
        :return: Decimal — размер позиции
        """
        try:
            stop_loss = self.get_stop_loss(signal=signal, price=price)
            if stop_loss is None:
                logger.warning("[RiskManager] Stop-loss не задан — размер позиции 0")
                return Decimal("0.0")

            stop_distance = abs(price - stop_loss)
            if stop_distance == 0:
                logger.warning(
                    "[RiskManager] Расстояние до стопа = 0 — размер позиции 0"
                )
                return Decimal("0.0")

            risk_fraction = self.max_risk_per_trade / Decimal("100")
            risk_amount = balance * risk_fraction
            position_size = risk_amount / stop_distance

            logger.debug(
                f"[RiskManager] stop_loss={stop_loss}, stop_distance={stop_distance}, "
                f"risk_amount={risk_amount}, position_size={position_size}"
            )

            return position_size
        except (InvalidOperation, DivisionByZero) as e:
            logger.error(f"[RiskManager] Ошибка расчёта позиции: {e}")
            return Decimal("0.0")

    def load_data(self, data: dict[str, Any]) -> None:
        """
        Загружает данные риск-менеджера из словаря.

        :param data: Словарь с данными
        """
        candles = data.get("candles", [])
        self.candles = [
            CandleDTO(
                dt_unix=candle["dt_unix"],
                open=candle["open"],
                high=candle["high"],
                low=candle["low"],
                close=candle["close"],
                volume=candle["volume"],
            )
            for candle in candles
        ]
        logger.debug(f"[RiskManager] Данные загружены: {data}")

    def dump_data(self) -> dict[str, Any]:
        """
        Сериализует состояние риск-менеджера в словарь.

        :return: Словарь с данными
        """
        data = {}
        logger.debug(f"[RiskManager] Данные сериализованы: {data}")
        return data
