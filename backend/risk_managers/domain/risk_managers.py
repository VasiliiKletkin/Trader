from decimal import Decimal, DivisionByZero, InvalidOperation
from typing import Any, List, Optional
import pandas as pd
from loguru import logger
from backend.exchanges.domain.schemas import CandleDTO
from .base import AbstractRiskManager, SignalType
from .schemas import PositionType


class StopLossNoneMixin:
    """
    Миксин: стоп-лосс не устанавливается.
    """

    def get_stop_loss(self, signal: SignalType, price: Decimal) -> Optional[Decimal]:
        logger.debug(
            f"[StopLossNoneMixin] Стоп-лосс не установлен. Сигнал: {signal}, Цена: {price}"
        )
        return None


class StopLossRenkoMixin:
    """
    Миксин: стоп-лосс по процентным порогам (Renko).

    :param trashold_up: Процент для стоп-лосса при шорте (>= 0)
    :param trashold_down: Процент для стоп-лосса при лонге (>= 0)
    Значения должны быть неотрицательными.
    """

    def __init__(
        self, trashold_up: float = 1.0, trashold_down: float = 1.0, *args, **kwargs
    ):
        """
        :param trashold_up: Процент для стоп-лосса при шорте (>= 0)
        :param trashold_down: Процент для стоп-лосса при лонге (>= 0)
        """
        try:
            self.trashold_up = Decimal(str(trashold_up))
            self.trashold_down = Decimal(str(trashold_down))
            if self.trashold_up < 0 or self.trashold_down < 0:
                raise ValueError("Пороговые значения должны быть неотрицательными.")
        except Exception as e:
            logger.error(
                f"[StopLossRenkoMixin] Некорректные параметры trashold_up/trashold_down: {e} (передано: trashold_up={trashold_up}, trashold_down={trashold_down})"
            )
            raise
        super().__init__(*args, **kwargs)

    def get_stop_loss(self, signal: SignalType, price: Decimal) -> Optional[Decimal]:
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
                logger.warning(
                    f"[StopLossRenkoMixin] Неизвестный тип позиции: {position_type}"
                )
                return None
            logger.debug(
                f"[StopLossRenkoMixin] Стоп-лосс для {position_type}: {stop_loss:.4f}"
            )
            return stop_loss
        except (InvalidOperation, TypeError, AttributeError) as e:
            logger.error(f"[StopLossRenkoMixin] Ошибка при расчёте стоп-лосса: {e}")
            return None


class StopLossExtremumMixin:
    """
    Миксин: стоп-лосс по экстремумам (минимум/максимум) последних N свечей.
    Требует: self.candles (список CandleDTO, минимум 1 элемент).
    Для LONG — стоп-лосс по минимуму, для SHORT — по максимуму.
    """

    def __init__(self, *args, **kwargs):
        self.candles: List[CandleDTO] = []
        super().__init__(*args, **kwargs)

    def get_stop_loss(self, signal: SignalType, price: Decimal) -> Optional[Decimal]:
        try:
            position_type = self.get_position_type(signal)
            if not self.candles:
                logger.warning(
                    "[StopLossExtremumMixin] Нет данных по свечам для расчёта стоп-лосса."
                )
                return None
            df_candles = pd.DataFrame(
                [c.model_dump(exclude="dt_unix") for c in self.candles[-5:]]
            )
            if position_type == PositionType.LONG:
                stop_loss = df_candles["low"].min()
            elif position_type == PositionType.SHORT:
                stop_loss = df_candles["high"].max()
            else:
                logger.warning(
                    f"[StopLossExtremumMixin] Неизвестный тип позиции: {position_type}"
                )
                return None
            logger.debug(
                f"[StopLossExtremumMixin] Стоп-лосс для {position_type}: {stop_loss:.4f}"
            )
            return stop_loss
        except Exception as e:
            logger.error(f"[StopLossExtremumMixin] Ошибка при расчёте стоп-лосса: {e}")
            return None

    def load_data(self, data: dict[str, Any]) -> None:
        self.candles = [
            CandleDTO(
                dt_unix=candle["dt_unix"],
                open=candle["open"],
                high=candle["high"],
                low=candle["low"],
                close=candle["close"],
                volume=candle["volume"],
            )
            for candle in data.get("candles", [])
        ]
        logger.debug(f"[StopLossExtremumMixin] Загружено свечей: {len(self.candles)}")


# --- Миксины для take_profit ---


class TakeProfitNoneMixin:
    """
    Миксин: тейк-профит не устанавливается.
    """

    def get_take_profit(self, signal: SignalType, price: Decimal) -> Optional[Decimal]:
        logger.debug(
            f"[TakeProfitNoneMixin] Тейк-профит не установлен. Сигнал: {signal}, Цена: {price}"
        )
        return None


class TakeProfitRiskRewardMixin:
    """
    Миксин: тейк-профит по risk/reward (Renko).

    :param rr_ratio: Соотношение reward/risk (должно быть > 0, например 2.0 — тейк-профит в 2 раза дальше стоп-лосса)
    """

    def __init__(self, rr_ratio: float = 2.0, *args, **kwargs):
        """
        :param rr_ratio: Соотношение reward/risk (> 0)
        """
        try:
            self.rr_ratio = Decimal(str(rr_ratio))
            if self.rr_ratio <= 0:
                raise ValueError("rr_ratio должен быть положительным числом.")
        except Exception as e:
            logger.error(
                f"[TakeProfitRiskRewardMixin] Некорректный rr_ratio: {e} (передано: {rr_ratio})"
            )
            raise
        super().__init__(*args, **kwargs)

    def get_take_profit(self, signal: SignalType, price: Decimal) -> Optional[Decimal]:
        try:
            stop_loss = self.get_stop_loss(signal=signal, price=price)
            if stop_loss is None or price is None or not self.rr_ratio:
                logger.warning(
                    f"[TakeProfitRenkoMixin] Недостаточно данных для расчёта тейк-профита."
                )
                return None
            position_type = self.get_position_type(signal)
            risk_distance = abs(price - stop_loss)
            reward_distance = risk_distance * Decimal(str(self.rr_ratio))
            if position_type == PositionType.LONG:
                take_profit = price + reward_distance
            elif position_type == PositionType.SHORT:
                take_profit = price - reward_distance
            else:
                logger.warning(
                    f"[TakeProfitRenkoMixin] Неизвестный тип позиции: {position_type}"
                )
                return None
            logger.debug(
                f"[TakeProfitRenkoMixin] Тейк-профит для {position_type}: {take_profit:.4f} "
                f"(риск: {risk_distance:.4f}, rr: {self.rr_ratio})"
            )
            return take_profit
        except (InvalidOperation, TypeError, AttributeError) as e:
            logger.error(f"[TakeProfitRenkoMixin] Ошибка при расчёте тейк-профита: {e}")
            return None


# --- Миксины для position_size ---


class PositionSizeAllInMixin:
    """
    Миксин: размер позиции — весь баланс по текущей цене.
    """

    def calculate_position_size(
        self, signal: SignalType, price: Decimal, balance: Decimal
    ) -> Decimal:
        try:
            result = balance / price
            logger.debug(
                f"[PositionSizeAllInMixin] Размер позиции: {result:.4f} (баланс={balance}, цена={price})"
            )
            return result
        except DivisionByZero:
            logger.error(f"[PositionSizeAllInMixin] Деление на ноль: цена={price}")
            return Decimal("0.0")


class PositionSizeByRiskMixin:
    """
    Миксин: размер позиции по риску и стоп-лоссу.

    :param max_risk_per_trade: Максимальный риск на сделку в процентах от баланса (0 < x <= 100).
        Например, если max_risk_per_trade=1.5, то риск на сделку — 1.5% от баланса.
        Значение должно быть положительным и не превышать 100.
    """

    def __init__(self, max_risk_per_trade: float = 1.5, *args, **kwargs):
        """
        :param max_risk_per_trade: Максимальный риск на сделку в процентах от баланса (0 < x <= 100).
        """
        try:
            self.max_risk_per_trade = Decimal(str(max_risk_per_trade))
            if self.max_risk_per_trade <= 0 or self.max_risk_per_trade > 100:
                raise ValueError(
                    "max_risk_per_trade должен быть в диапазоне (0, 100] процентов от баланса."
                )
        except Exception as e:
            logger.error(
                f"[PositionSizeByRiskMixin] Некорректный max_risk_per_trade: {e} (передано: {max_risk_per_trade})"
            )
            raise
        super().__init__(*args, **kwargs)

    def calculate_position_size(
        self, signal: SignalType, price: Decimal, balance: Decimal
    ) -> Decimal:
        try:
            stop_loss = self.get_stop_loss(signal=signal, price=price)
            if stop_loss is None:
                logger.warning(
                    "[PositionSizeByRiskMixin] Стоп-лосс не установлен — размер позиции 0"
                )
                return Decimal("0.0")
            stop_distance = abs(price - stop_loss)
            if stop_distance == 0:
                logger.warning(
                    "[PositionSizeByRiskMixin] Расстояние до стоп-лосса 0 — размер позиции 0"
                )
                return Decimal("0.0")
            risk_fraction = self.max_risk_per_trade / Decimal("100")
            risk_amount = balance * risk_fraction
            position_size = risk_amount / stop_distance
            logger.debug(
                f"[PositionSizeByRiskMixin] stop_loss={stop_loss}, stop_distance={stop_distance}, "
                f"risk_amount={risk_amount}, размер позиции={position_size}"
            )
            return position_size
        except (InvalidOperation, DivisionByZero, AttributeError) as e:
            logger.error(
                f"[PositionSizeByRiskMixin] Ошибка при расчёте размера позиции: {e}"
            )
            return Decimal("0.0")


class RiskManagerBaseMixin:
    """
    Базовый миксин для общих методов риск-менеджера.

    :param max_positions_count: Максимальное количество одновременно открытых позиций (>= 1)
    :param max_drawdown_pct: Максимально допустимая просадка в процентах от начального баланса (0 < x <= 100)
    """

    def __init__(
        self,
        max_positions_count: int = 1,
        max_drawdown_pct: float = 20.0,
        *args,
        **kwargs,
    ):
        """
        :param max_positions_count: Максимальное количество одновременно открытых позиций (>= 1)
        :param max_drawdown_pct: Максимально допустимая просадка в процентах от начального баланса (0 < x <= 100)
        """
        try:
            self.max_positions_count = int(max_positions_count)
            self.max_drawdown_pct = float(max_drawdown_pct)
            if self.max_positions_count < 1:
                raise ValueError("max_positions_count должен быть >= 1.")
            if not (0 < self.max_drawdown_pct <= 100):
                raise ValueError("max_drawdown_pct должен быть в диапазоне (0, 100].")
        except Exception as e:
            logger.error(
                f"[RiskManagerBaseMixin] Некорректные параметры: {e} (передано: max_positions_count={max_positions_count}, max_drawdown_pct={max_drawdown_pct})"
            )
            raise
        super().__init__(*args, **kwargs)

    def can_trade(
        self,
        signal: SignalType,
        price: Decimal,
        balance: Decimal,
        opened_positions: List[Any],
        initial_balance: Decimal,
    ) -> bool:
        if signal not in {SignalType.BUY, SignalType.SELL}:
            logger.info(
                f"[RiskManagerBaseMixin] Сигнал {signal} не разрешён для торговли."
            )
            return False
        if not self.check_drawdown_limit(balance, initial_balance):
            logger.info(f"[RiskManagerBaseMixin] Превышен лимит просадки.")
            return False
        if not self.check_max_positions(opened_positions):
            logger.info(
                f"[RiskManagerBaseMixin] Достигнут лимит по количеству позиций."
            )
            return False
        logger.debug(f"[RiskManagerBaseMixin] Торговля разрешена.")
        return True

    def get_position_type(self, signal: SignalType) -> Optional[str]:
        if signal == SignalType.BUY:
            return PositionType.LONG
        elif signal == SignalType.SELL:
            return PositionType.SHORT
        logger.warning(f"[RiskManagerBaseMixin] Неизвестный сигнал: {signal}")
        return None

    def check_max_positions(self, opened_positions: List[Any]) -> bool:
        result = len(opened_positions) < self.max_positions_count
        logger.debug(
            f"[RiskManagerBaseMixin] Открыто позиций: {len(opened_positions)}, Макс. разрешено: {self.max_positions_count}, Результат: {result}"
        )
        return result

    def check_drawdown_limit(self, balance: Decimal, initial_balance: Decimal) -> bool:
        try:
            allowed_min_balance = initial_balance * (
                1 - Decimal(str(self.max_drawdown_pct)) / Decimal("100")
            )
            result = balance >= allowed_min_balance
            logger.debug(
                f"[RiskManagerBaseMixin] Баланс: {balance}, Минимально допустимый: {allowed_min_balance}, Результат: {result}"
            )
            return result
        except (InvalidOperation, TypeError) as e:
            logger.error(f"[RiskManagerBaseMixin] Ошибка при проверке просадки: {e}")
            return False

    def load_data(self, data: dict[str, Any]) -> None:
        logger.debug(f"[RiskManagerBaseMixin] Данные загружены: {data}")

    def dump_data(self) -> dict[str, Any]:
        data = {}
        logger.debug(f"[RiskManagerBaseMixin] Данные выгружены: {data}")
        return data


class NoSLNoTPAllInManager(
    StopLossNoneMixin,
    TakeProfitNoneMixin,
    PositionSizeAllInMixin,
    RiskManagerBaseMixin,
    AbstractRiskManager,
):
    """
    Риск-менеджер: без стоп-лосса, без тейк-профита, весь баланс.
    - Нет стоп-лосса
    - Нет тейк-профита
    - Размер позиции: весь баланс
    """

    pass


class NoSLNoTPByRiskManager(
    StopLossNoneMixin,
    TakeProfitNoneMixin,
    PositionSizeByRiskMixin,
    RiskManagerBaseMixin,
    AbstractRiskManager,
):
    """
    Риск-менеджер: без стоп-лосса, без тейк-профита, размер позиции по риску.
    - Нет стоп-лосса
    - Нет тейк-профита
    - Размер позиции по риску
    """

    pass


class NoSLTPRRAllInManager(
    StopLossNoneMixin,
    TakeProfitRiskRewardMixin,
    PositionSizeAllInMixin,
    RiskManagerBaseMixin,
    AbstractRiskManager,
):
    """
    Риск-менеджер: без стоп-лосса, тейк-профит по risk/reward, весь баланс.
    - Нет стоп-лосса
    - Тейк-профит по risk/reward
    - Размер позиции: весь баланс
    """

    pass


class NoSLTPRRByRiskManager(
    StopLossNoneMixin,
    TakeProfitRiskRewardMixin,
    PositionSizeByRiskMixin,
    RiskManagerBaseMixin,
    AbstractRiskManager,
):
    """
    Риск-менеджер: без стоп-лосса, тейк-профит по risk/reward, размер позиции по риску.
    - Нет стоп-лосса
    - Тейк-профит по risk/reward
    - Размер позиции по риску
    """

    pass


class RenkoNoTPAllInManager(
    StopLossRenkoMixin,
    TakeProfitNoneMixin,
    PositionSizeAllInMixin,
    RiskManagerBaseMixin,
    AbstractRiskManager,
):
    """
    Риск-менеджер: стоп-лосс Renko, без тейк-профита, весь баланс.
    - Стоп-лосс по проценту (Renko)
    - Нет тейк-профита
    - Размер позиции: весь баланс
    """

    pass


class RenkoNoTPByRiskManager(
    StopLossRenkoMixin,
    TakeProfitNoneMixin,
    PositionSizeByRiskMixin,
    RiskManagerBaseMixin,
    AbstractRiskManager,
):
    """
    Риск-менеджер: стоп-лосс Renko, без тейк-профита, размер позиции по риску.
    - Стоп-лосс по проценту (Renko)
    - Нет тейк-профита
    - Размер позиции по риску
    """

    pass


class RenkoTPRRAllInManager(
    StopLossRenkoMixin,
    TakeProfitRiskRewardMixin,
    PositionSizeAllInMixin,
    RiskManagerBaseMixin,
    AbstractRiskManager,
):
    """
    Риск-менеджер: стоп-лосс Renko, тейк-профит по risk/reward, весь баланс.
    - Стоп-лосс по проценту (Renko)
    - Тейк-профит по risk/reward
    - Размер позиции: весь баланс
    """

    pass


class RenkoTPRRByRiskManager(
    StopLossRenkoMixin,
    TakeProfitRiskRewardMixin,
    PositionSizeByRiskMixin,
    RiskManagerBaseMixin,
    AbstractRiskManager,
):
    """
    Риск-менеджер: стоп-лосс Renko, тейк-профит по risk/reward, размер позиции по риску.
    - Стоп-лосс по проценту (Renko)
    - Тейк-профит по risk/reward
    - Размер позиции по риску
    """

    pass


class ExtremumNoTPAllInManager(
    StopLossExtremumMixin,
    TakeProfitNoneMixin,
    PositionSizeAllInMixin,
    RiskManagerBaseMixin,
    AbstractRiskManager,
):
    """
    Риск-менеджер: стоп-лосс по экстремумам, без тейк-профита, весь баланс.
    - Стоп-лосс по экстремумам последних свечей
    - Нет тейк-профита
    - Размер позиции: весь баланс
    """

    pass


class ExtremumNoTPByRiskManager(
    StopLossExtremumMixin,
    TakeProfitNoneMixin,
    PositionSizeByRiskMixin,
    RiskManagerBaseMixin,
    AbstractRiskManager,
):
    """
    Риск-менеджер: стоп-лосс по экстремумам, без тейк-профита, размер позиции по риску.
    - Стоп-лосс по экстремумам последних свечей
    - Нет тейк-профита
    - Размер позиции по риску
    """

    pass


class ExtremumTPRRAllInManager(
    StopLossExtremumMixin,
    TakeProfitRiskRewardMixin,
    PositionSizeAllInMixin,
    RiskManagerBaseMixin,
    AbstractRiskManager,
):
    """
    Риск-менеджер: стоп-лосс по экстремумам, тейк-профит по risk/reward, весь баланс.
    - Стоп-лосс по экстремумам последних свечей
    - Тейк-профит по risk/reward
    - Размер позиции: весь баланс
    """

    pass


class ExtremumTPRRByRiskManager(
    StopLossExtremumMixin,
    TakeProfitRiskRewardMixin,
    PositionSizeByRiskMixin,
    RiskManagerBaseMixin,
    AbstractRiskManager,
):
    """
    Риск-менеджер: стоп-лосс по экстремумам, тейк-профит по risk/reward, размер позиции по риску.
    - Стоп-лосс по экстремумам последних свечей
    - Тейк-профит по risk/reward
    - Размер позиции по риску
    """

    pass
