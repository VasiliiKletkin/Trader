from decimal import Decimal
from typing import Any, List, Optional

import pandas as pd
from exchanges.domain.schemas import Candle
from loguru import logger

from .base import AbstractRiskManager
from .schemas import PositionType


class StopLossNoneMixin:
    """
    Миксин: стоп-лосс не устанавливается.
    """

    def get_stop_loss(
        self, position_type: PositionType, price: Decimal
    ) -> Optional[Decimal]:
        return None


class StopLossPercentMixin:
    """
    Миксин: стоп-лосс по проценту от цены.
    """

    def __init__(self, stop_loss_percent: float = 1.0, *args, **kwargs):
        self.stop_loss_percent = Decimal(str(stop_loss_percent))
        if self.stop_loss_percent < 0 or self.stop_loss_percent > 100:
            raise ValueError("stop_loss_percent должен быть в диапазоне [0, 100].")
        super().__init__(*args, **kwargs)

    def get_stop_loss(
        self, position_type: PositionType, price: Decimal
    ) -> Optional[Decimal]:
        logger.debug(
            f"get_stop_loss: type={position_type}, price={price}, percent={self.stop_loss_percent}"
        )
        if position_type == PositionType.LONG:
            stop_loss = price - (price * self.stop_loss_percent / Decimal("100"))
        elif position_type == PositionType.SHORT:
            stop_loss = price + (price * self.stop_loss_percent / Decimal("100"))
        logger.debug(f"stop_loss={stop_loss}")
        return stop_loss


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
        self.trashold_up = Decimal(str(trashold_up))
        self.trashold_down = Decimal(str(trashold_down))
        if self.trashold_up < 0 or self.trashold_down < 0:
            raise ValueError("Пороговые значения должны быть неотрицательными.")
        super().__init__(*args, **kwargs)

    def get_stop_loss(
        self, position_type: PositionType, price: Decimal
    ) -> Optional[Decimal]:
        logger.debug(
            f"get_stop_loss: type={position_type}, price={price}, trashold_up={self.trashold_up}, trashold_down={self.trashold_down}"
        )
        if position_type == PositionType.LONG:
            stop_loss = price - (
                price * Decimal(str(self.trashold_down)) / Decimal("100")
            )
        elif position_type == PositionType.SHORT:
            stop_loss = price + (
                price * Decimal(str(self.trashold_up)) / Decimal("100")
            )
        logger.debug(f"stop_loss={stop_loss}")
        return stop_loss


class StopLossExtremumMixin:
    """
    Миксин: стоп-лосс по экстремумам (минимум/максимум) последних N свечей.
    Требует: self.candles (список Candle, минимум 1 элемент).
    Для LONG — стоп-лосс по минимуму, для SHORT — по максимуму.
    """

    def __init__(self, extremum_candle_length: int = 5, *args, **kwargs):
        """
        :param extremum_candle_length: Количество последних свечей для поиска экстремума (>=1)
        """
        if not isinstance(extremum_candle_length, int):
            raise TypeError("extremum_candle_length должен быть целым числом.")
        if extremum_candle_length < 1:
            raise ValueError("extremum_candle_length должен быть >= 1.")
        self.extremum_candle_length = extremum_candle_length
        self.candles: List[Candle] = []
        super().__init__(*args, **kwargs)

    def get_stop_loss(
        self, position_type: PositionType, price: Decimal
    ) -> Optional[Decimal]:
        logger.debug(
            f"get_stop_loss: type={position_type}, price={price}, extremum_candle_length={self.extremum_candle_length}"
        )
        if not self.candles:
            logger.warning("Нет данных по свечам для расчёта стоп-лосса.")
            return None
        df_candles = pd.DataFrame(
            [
                c.model_dump(exclude="dt_unix")
                for c in self.candles[-self.extremum_candle_length :]
            ]
        )
        if position_type == PositionType.LONG:
            stop_loss = df_candles["low"].min()
        elif position_type == PositionType.SHORT:
            stop_loss = df_candles["high"].max()
        logger.debug(f"stop_loss={stop_loss}")
        return stop_loss

    def load_data(self, data: dict[str, Any]) -> None:
        self.candles = [
            Candle(
                dt_unix=candle["dt_unix"],
                open=candle["open"],
                high=candle["high"],
                low=candle["low"],
                close=candle["close"],
                volume=candle["volume"],
            )
            for candle in data.get("candles", [])
        ]


# --- Миксины для take_profit ---


class TakeProfitNoneMixin:
    """
    Миксин: тейк-профит не устанавливается.
    """

    def get_take_profit(
        self, position_type: PositionType, price: Decimal
    ) -> Optional[Decimal]:
        return None


class TakeProfitPercentMixin:
    """
    Миксин: тейк-профит по проценту от цены.

    :param take_profit_percent: Процент для тейк-профита (>= 0)
    """

    def __init__(self, take_profit_percent: float = 1.0, *args, **kwargs):
        self.take_profit_percent = Decimal(str(take_profit_percent))
        if self.take_profit_percent < 0:
            raise ValueError(f"take_profit_percent должен быть в отрезке [0,100].")
        super().__init__(*args, **kwargs)

    def get_take_profit(
        self, position_type: PositionType, price: Decimal
    ) -> Optional[Decimal]:
        logger.debug(
            f"get_take_profit: type={position_type}, price={price}, percent={self.take_profit_percent}"
        )
        if position_type == PositionType.LONG:
            take_profit = price + (price * self.take_profit_percent / Decimal("100"))
        elif position_type == PositionType.SHORT:
            take_profit = price - (price * self.take_profit_percent / Decimal("100"))
        logger.debug(f"take_profit={take_profit}")
        return take_profit


class TakeProfitRiskRewardMixin:
    """
    Миксин: тейк-профит по risk/reward (Renko).

    :param rr_ratio: Соотношение reward/risk (должно быть > 0, например 2.0 — тейк-профит в 2 раза дальше стоп-лосса)
    """

    def __init__(self, rr_ratio: float = 2.0, *args, **kwargs):
        """
        :param rr_ratio: Соотношение reward/risk (> 0)
        """
        self.rr_ratio = Decimal(str(rr_ratio))
        if self.rr_ratio <= 0:
            raise ValueError("rr_ratio должен быть положительным числом.")
        super().__init__(*args, **kwargs)

    def get_take_profit(
        self, position_type: PositionType, price: Decimal
    ) -> Optional[Decimal]:
        logger.debug(
            f"get_take_profit: type={position_type}, price={price}, rr_ratio={self.rr_ratio}"
        )
        stop_loss = self.get_stop_loss(position_type=position_type, price=price)
        if stop_loss is None or price is None or not self.rr_ratio:
            logger.warning(f"stop_loss or rr_ratio is None")
            return None
        risk_distance = abs(price - stop_loss)
        reward_distance = risk_distance * Decimal(str(self.rr_ratio))
        if position_type == PositionType.LONG:
            take_profit = price + reward_distance
        elif position_type == PositionType.SHORT:
            take_profit = price - reward_distance
        logger.debug(f"take_profit={take_profit}")
        return take_profit


# --- Миксины для position_size ---


class PositionSizeAllInMixin:
    """
    Миксин: размер позиции — весь баланс по текущей цене.
    """

    def calculate_position_size(
        self, position_type: PositionType, price: Decimal, balance: Decimal
    ) -> Decimal:
        size = balance / price
        logger.debug(
            f"calculate_position_size: type={position_type}, price={price}, balance={balance}, size={size}"
        )
        return size


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
        self.max_risk_per_trade = Decimal(str(max_risk_per_trade))
        if self.max_risk_per_trade <= 0 or self.max_risk_per_trade > 100:
            raise ValueError(
                "max_risk_per_trade должен быть в диапазоне (0, 100] процентов от баланса."
            )
        super().__init__(*args, **kwargs)

    def calculate_position_size(
        self, position_type: PositionType, price: Decimal, balance: Decimal
    ) -> Decimal:
        stop_loss = self.get_stop_loss(position_type=position_type, price=price)
        logger.debug(
            f"calculate_position_size: type={position_type}, price={price}, balance={balance}, stop_loss={stop_loss}, max_risk_per_trade={self.max_risk_per_trade}"
        )
        if stop_loss is None:
            logger.warning(f"stop_loss is None")
            return Decimal("0.0")
        stop_distance = abs(price - stop_loss)
        if stop_distance == 0:
            logger.warning(f"stop_distance is 0")
            return Decimal("0.0")
        risk_fraction = self.max_risk_per_trade / Decimal("100")
        risk_amount = balance * risk_fraction
        position_size = risk_amount / stop_distance
        logger.debug(f"position_size={position_size}")
        return position_size


class PositionSizeLimitMixin:
    """
    Миксин: ограничивает размер позиции максимальным возможным количеством актива на баланс.
    Должен быть последним в цепочке миксинов position_size.
    """

    def calculate_position_size(
        self, position_type: PositionType, price: Decimal, balance: Decimal
    ) -> Decimal:
        size = super().calculate_position_size(
            position_type=position_type, price=price, balance=balance
        )
        logger.debug(
            f"calculate_position_size: type={position_type}, price={price}, balance={balance}, size(before_limit)={size}"
        )
        if price <= 0:
            logger.warning(f"price <= 0")
            return Decimal("0.0")
        max_size = balance / price
        if size > max_size:
            logger.debug(f"size limited: {size} -> {max_size}")
            return max_size
        return size


class RiskManagerBaseMixin:
    """
    Базовый миксин для общих методов риск-менеджера.
    """

    def load_data(self, data: dict[str, Any]) -> None:
        pass

    def dump_data(self) -> dict[str, Any]:
        data = {}
        return data


class SLPercentTPPercentAllInManager(
    StopLossPercentMixin,
    TakeProfitPercentMixin,
    PositionSizeLimitMixin,
    PositionSizeAllInMixin,
    RiskManagerBaseMixin,
    AbstractRiskManager,
):
    """
    Риск-менеджер: стоп-лосс и тейк-профит по проценту, весь баланс.
    - Стоп-лосс по проценту
    - Тейк-профит по проценту
    - Размер позиции: весь баланс
    """

    pass


class SLPercentTPPercentByRiskManager(
    StopLossPercentMixin,
    TakeProfitPercentMixin,
    PositionSizeLimitMixin,
    PositionSizeByRiskMixin,
    RiskManagerBaseMixin,
    AbstractRiskManager,
):
    """
    Риск-менеджер: стоп-лосс и тейк-профит по проценту, размер позиции по риску.
    - Стоп-лосс по проценту
    - Тейк-профит по проценту
    - Размер позиции по риску
    """

    pass


class SLPercentTPRRAllInManager(
    StopLossPercentMixin,
    TakeProfitRiskRewardMixin,
    PositionSizeLimitMixin,
    PositionSizeAllInMixin,
    RiskManagerBaseMixin,
    AbstractRiskManager,
):
    """
    Риск-менеджер: стоп-лосс по проценту, тейк-профит по risk/reward, весь баланс.
    - Стоп-лосс по проценту
    - Тейк-профит по risk/reward
    - Размер позиции: весь баланс
    """

    pass


class SLPercentTPRRByRiskManager(
    StopLossPercentMixin,
    TakeProfitRiskRewardMixin,
    PositionSizeLimitMixin,
    PositionSizeByRiskMixin,
    RiskManagerBaseMixin,
    AbstractRiskManager,
):
    """
    Риск-менеджер: стоп-лосс по проценту, тейк-профит по risk/reward, размер позиции по риску.
    - Стоп-лосс по проценту
    - Тейк-профит по risk/reward
    - Размер позиции по риску
    """

    pass


class NoSLNoTPAllInManager(
    StopLossNoneMixin,
    TakeProfitNoneMixin,
    PositionSizeLimitMixin,
    PositionSizeAllInMixin,
    RiskManagerBaseMixin,
    AbstractRiskManager,
):
    """
    Риск-менеджер: без стоп-лосс, без тейк-профита, весь баланс.
    - Нет стоп лосса
    - Нет тейк-профита
    - Размер позиции: весь баланс
    """

    pass


class RenkoNoTPAllInManager(
    StopLossRenkoMixin,
    TakeProfitNoneMixin,
    PositionSizeLimitMixin,
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
    PositionSizeLimitMixin,
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
    PositionSizeLimitMixin,
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
    PositionSizeLimitMixin,
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
    PositionSizeLimitMixin,
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
    PositionSizeLimitMixin,
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
    PositionSizeLimitMixin,
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
    PositionSizeLimitMixin,
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
