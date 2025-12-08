from decimal import Decimal
from typing import TYPE_CHECKING, Optional

import pandas as pd
from loguru import logger

from .base import AbstractRiskManager
from .schemas import PositionType

if TYPE_CHECKING:
    from traders.domain import Trader


class StopLossPercentMixin:
    """
    Миксин: стоп-лосс по проценту от цены.
    """

    PARAM_CONSTRAINTS = {'stop_loss_percent': (0.0, 100.0)}

    def __init__(self, stop_loss_percent: float = 1.0, *args, **kwargs):
        self.stop_loss_percent = Decimal(str(stop_loss_percent))
        if self.stop_loss_percent < 0 or self.stop_loss_percent > 100:
            raise ValueError("stop_loss_percent должен быть в диапазоне [0, 100].")
        super().__init__(*args, **kwargs)

    def get_stop_loss(
        self, trader: "Trader", position_type: PositionType, price: Decimal
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
    """

    PARAM_CONSTRAINTS = {'trashold_up': (0.0, 100.0), 'trashold_down': (0.0, 100.0)}

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
        self, trader: "Trader", position_type: PositionType, price: Decimal
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
    """

    PARAM_CONSTRAINTS = {'extremum_candle_length': (1, 100)}

    def __init__(self, extremum_candle_length: int = 5, *args, **kwargs):
        """
        :param extremum_candle_length: Количество последних свечей для поиска экстремума (>=1)
        """
        if not isinstance(extremum_candle_length, int):
            raise TypeError("extremum_candle_length должен быть целым числом.")
        if extremum_candle_length < 1:
            raise ValueError("extremum_candle_length должен быть >= 1.")
        self.extremum_candle_length = extremum_candle_length
        super().__init__(*args, **kwargs)

    def get_stop_loss(
        self, trader: "Trader", position_type: PositionType, price: Decimal
    ) -> Optional[Decimal]:
        logger.debug(
            f"get_stop_loss: type={position_type}, price={price}, extremum_candle_length={self.extremum_candle_length}"
        )

        # Получаем свечи от трейдера
        candles = trader.candles if trader else []

        if not candles:
            logger.warning("Нет данных по свечам для расчёта стоп-лосса.")
            return None

        df_candles = pd.DataFrame(
            [
                c.model_dump(exclude="dt_unix")
                for c in candles[-self.extremum_candle_length :]
            ]
        )

        if position_type == PositionType.LONG:
            stop_loss = df_candles["low"].min()
        elif position_type == PositionType.SHORT:
            stop_loss = df_candles["high"].max()

        logger.debug(f"stop_loss={stop_loss}")
        return stop_loss


# --- Миксины для take_profit ---

class TakeProfitPercentMixin:
    """
    Миксин: тейк-профит в процентах от цены открытия.
    """

    PARAM_CONSTRAINTS = {'take_profit_percent': (0.0, 100.0)}

    def __init__(self, take_profit_percent: float = 2.0, *args, **kwargs):
        """
        :param take_profit_percent: Процент тейк-профита (0.0 - 100.0).
        """
        if not isinstance(take_profit_percent, (int, float)):
            raise TypeError("take_profit_percent должен быть числом.")
        if not (0.0 <= take_profit_percent <= 100.0):
            raise ValueError("take_profit_percent должен быть в отрезке [0,100].")
        self.take_profit_percent = Decimal(str(take_profit_percent))
        super().__init__(*args, **kwargs)

    def get_take_profit(
        self, trader: "Trader", position_type: PositionType, price: Decimal
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
    """

    PARAM_CONSTRAINTS = {'rr_ratio': (0.1, 10.0)}

    def __init__(self, rr_ratio: float = 2.0, *args, **kwargs):
        """
        :param rr_ratio: Соотношение reward/risk (> 0)
        """
        self.rr_ratio = Decimal(str(rr_ratio))
        if self.rr_ratio <= 0:
            raise ValueError("rr_ratio должен быть положительным числом.")
        super().__init__(*args, **kwargs)

    def get_take_profit(
        self, trader: "Trader", position_type: PositionType, price: Decimal
    ) -> Optional[Decimal]:
        logger.debug(
            f"get_take_profit: type={position_type}, price={price}, rr_ratio={self.rr_ratio}"
        )
        stop_loss = self.get_stop_loss(trader, position_type=position_type, price=price)
        if stop_loss is None or price is None or not self.rr_ratio:
            logger.warning("stop_loss or rr_ratio is None")
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

    PARAM_CONSTRAINTS = {}

    def calculate_position_size(
        self,
        trader: "Trader",
        position_type: PositionType,
        price: Decimal,
        balance: Decimal,
    ) -> Decimal:
        size = balance / price
        logger.debug(
            f"calculate_position_size: type={position_type}, price={price}, balance={balance}, size={size}"
        )
        return size


class PositionSizeByRiskMixin:
    """
    Миксин: размер позиции по риску и стоп-лоссу.
    """

    PARAM_CONSTRAINTS = {'max_risk_per_trade': (0.1, 100.0)}

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
        self,
        trader: "Trader",
        position_type: PositionType,
        price: Decimal,
        balance: Decimal,
    ) -> Decimal:
        stop_loss = self.get_stop_loss(trader, position_type=position_type, price=price)
        logger.debug(
            f"calculate_position_size: type={position_type}, price={price}, balance={balance}, stop_loss={stop_loss}, max_risk_per_trade={self.max_risk_per_trade}"
        )
        if stop_loss is None:
            logger.warning("stop_loss is None")
            return Decimal("0.0")
        stop_distance = abs(price - stop_loss)
        if stop_distance == 0:
            logger.warning("stop_distance is 0")
            return Decimal("0.0")
        risk_fraction = self.max_risk_per_trade / Decimal("100")
        risk_amount = balance * risk_fraction
        position_size = risk_amount / stop_distance
        logger.debug(f"position_size={position_size}")
        return position_size


class PositionSizeLimitMixin:
    """
    Миксин: ограничивает размер позиции максимальным возможным количеством актива на баланс.
    """

    PARAM_CONSTRAINTS = {}

    def calculate_position_size(
        self,
        trader: "Trader",
        position_type: PositionType,
        price: Decimal,
        balance: Decimal,
    ) -> Decimal:
        size = super().calculate_position_size(
            trader, position_type=position_type, price=price, balance=balance
        )
        logger.debug(
            f"calculate_position_size: type={position_type}, price={price}, balance={balance}, size(before_limit)={size}"
        )
        if price <= 0:
            logger.warning("price <= 0")
            return Decimal("0.0")
        max_size = balance / price
        if size > max_size:
            logger.debug(f"size limited: {size} -> {max_size}")
            return max_size
        return size


# --- Все вариации RiskManager ---


class SLPercentTPPercentPSAllInRiskManager(
    StopLossPercentMixin,
    TakeProfitPercentMixin,
    PositionSizeLimitMixin,
    PositionSizeAllInMixin,
    AbstractRiskManager,
):
    """
    Риск-менеджер: стоп-лосс по проценту, тейк-профит по проценту, весь баланс.
    """
    PARAM_CONSTRAINTS = {
        **StopLossPercentMixin.PARAM_CONSTRAINTS,
        **TakeProfitPercentMixin.PARAM_CONSTRAINTS,
        **PositionSizeLimitMixin.PARAM_CONSTRAINTS,
        **PositionSizeAllInMixin.PARAM_CONSTRAINTS,
    }


class SLPercentTPPercentPSByRiskRiskManager(
    StopLossPercentMixin,
    TakeProfitPercentMixin,
    PositionSizeLimitMixin,
    PositionSizeByRiskMixin,
    AbstractRiskManager,
):
    """
    Риск-менеджер: стоп-лосс по проценту, тейк-профит по проценту, размер позиции по риску.
    """
    PARAM_CONSTRAINTS = {
        **StopLossPercentMixin.PARAM_CONSTRAINTS,
        **TakeProfitPercentMixin.PARAM_CONSTRAINTS,
        **PositionSizeLimitMixin.PARAM_CONSTRAINTS,
        **PositionSizeByRiskMixin.PARAM_CONSTRAINTS,
    }


class SLPercentTPRiskRewardPSAllInRiskManager(
    StopLossPercentMixin,
    TakeProfitRiskRewardMixin,
    PositionSizeLimitMixin,
    PositionSizeAllInMixin,
    AbstractRiskManager,
):
    """
    Риск-менеджер: стоп-лосс по проценту, тейк-профит по risk/reward, весь баланс.
    """
    PARAM_CONSTRAINTS = {
        **StopLossPercentMixin.PARAM_CONSTRAINTS,
        **TakeProfitRiskRewardMixin.PARAM_CONSTRAINTS,
        **PositionSizeLimitMixin.PARAM_CONSTRAINTS,
        **PositionSizeAllInMixin.PARAM_CONSTRAINTS,
    }


class SLPercentTPRiskRewardPSByRiskRiskManager(
    StopLossPercentMixin,
    TakeProfitRiskRewardMixin,
    PositionSizeLimitMixin,
    PositionSizeByRiskMixin,
    AbstractRiskManager,
):
    """
    Риск-менеджер: стоп-лосс по проценту, тейк-профит по risk/reward, размер позиции по риску.
    """
    PARAM_CONSTRAINTS = {
        **StopLossPercentMixin.PARAM_CONSTRAINTS,
        **TakeProfitRiskRewardMixin.PARAM_CONSTRAINTS,
        **PositionSizeLimitMixin.PARAM_CONSTRAINTS,
        **PositionSizeByRiskMixin.PARAM_CONSTRAINTS,
    }


# class SLRenkoTPPercentPSAllInRiskManager(
#     StopLossRenkoMixin,
#     TakeProfitPercentMixin,
#     PositionSizeLimitMixin,
#     PositionSizeAllInMixin,
#     AbstractRiskManager,
# ):
#     """
#     Риск-менеджер: стоп-лосс по Renko, тейк-профит по проценту, весь баланс.
#     """
#     PARAM_CONSTRAINTS = {
#         **StopLossRenkoMixin.PARAM_CONSTRAINTS,
#         **TakeProfitPercentMixin.PARAM_CONSTRAINTS,
#         **PositionSizeLimitMixin.PARAM_CONSTRAINTS,
#         **PositionSizeAllInMixin.PARAM_CONSTRAINTS,
#     }


# class SLRenkoTPPercentPSByRiskRiskManager(
#     StopLossRenkoMixin,
#     TakeProfitPercentMixin,
#     PositionSizeLimitMixin,
#     PositionSizeByRiskMixin,
#     AbstractRiskManager,
# ):
#     """
#     Риск-менеджер: стоп-лосс по Renko, тейк-профит по проценту, размер позиции по риску.
#     """
#     PARAM_CONSTRAINTS = {
#         **StopLossRenkoMixin.PARAM_CONSTRAINTS,
#         **TakeProfitPercentMixin.PARAM_CONSTRAINTS,
#         **PositionSizeLimitMixin.PARAM_CONSTRAINTS,
#         **PositionSizeByRiskMixin.PARAM_CONSTRAINTS,
#     }


# class SLRenkoTPRiskRewardPSAllInRiskManager(
#     StopLossRenkoMixin,
#     TakeProfitRiskRewardMixin,
#     PositionSizeLimitMixin,
#     PositionSizeAllInMixin,
#     AbstractRiskManager,
# ):
#     """
#     Риск-менеджер: стоп-лосс по Renko, тейк-профит по risk/reward, весь баланс.
#     """
#     PARAM_CONSTRAINTS = {
#         **StopLossRenkoMixin.PARAM_CONSTRAINTS,
#         **TakeProfitRiskRewardMixin.PARAM_CONSTRAINTS,
#         **PositionSizeLimitMixin.PARAM_CONSTRAINTS,
#         **PositionSizeAllInMixin.PARAM_CONSTRAINTS,
#     }


# class SLRenkoTPRiskRewardPSByRiskRiskManager(
#     StopLossRenkoMixin,
#     TakeProfitRiskRewardMixin,
#     PositionSizeLimitMixin,
#     PositionSizeByRiskMixin,
#     AbstractRiskManager,
# ):
#     """
#     Риск-менеджер: стоп-лосс по Renko, тейк-профит по risk/reward, размер позиции по риску.
#     """
#     PARAM_CONSTRAINTS = {
#         **StopLossRenkoMixin.PARAM_CONSTRAINTS,
#         **TakeProfitRiskRewardMixin.PARAM_CONSTRAINTS,
#         **PositionSizeLimitMixin.PARAM_CONSTRAINTS,
#         **PositionSizeByRiskMixin.PARAM_CONSTRAINTS,
#     }


class SLExtremumTPPercentPSAllInRiskManager(
    StopLossExtremumMixin,
    TakeProfitPercentMixin,
    PositionSizeLimitMixin,
    PositionSizeAllInMixin,
    AbstractRiskManager,
):
    """
    Риск-менеджер: стоп-лосс по экстремумам, тейк-профит по проценту, весь баланс.
    """
    PARAM_CONSTRAINTS = {
        **StopLossExtremumMixin.PARAM_CONSTRAINTS,
        **TakeProfitPercentMixin.PARAM_CONSTRAINTS,
        **PositionSizeLimitMixin.PARAM_CONSTRAINTS,
        **PositionSizeAllInMixin.PARAM_CONSTRAINTS,
    }


class SLExtremumTPPercentPSByRiskRiskManager(
    StopLossExtremumMixin,
    TakeProfitPercentMixin,
    PositionSizeLimitMixin,
    PositionSizeByRiskMixin,
    AbstractRiskManager,
):
    """
    Риск-менеджер: стоп-лосс по экстремумам, тейк-профит по проценту, размер позиции по риску.
    """
    PARAM_CONSTRAINTS = {
        **StopLossExtremumMixin.PARAM_CONSTRAINTS,
        **TakeProfitPercentMixin.PARAM_CONSTRAINTS,
        **PositionSizeLimitMixin.PARAM_CONSTRAINTS,
        **PositionSizeByRiskMixin.PARAM_CONSTRAINTS,
    }


class SLExtremumTPRiskRewardPSAllInRiskManager(
    StopLossExtremumMixin,
    TakeProfitRiskRewardMixin,
    PositionSizeLimitMixin,
    PositionSizeAllInMixin,
    AbstractRiskManager,
):
    """
    Риск-менеджер: стоп-лосс по экстремумам, тейк-профит по risk/reward, весь баланс.
    """
    PARAM_CONSTRAINTS = {
        **StopLossExtremumMixin.PARAM_CONSTRAINTS,
        **TakeProfitRiskRewardMixin.PARAM_CONSTRAINTS,
        **PositionSizeLimitMixin.PARAM_CONSTRAINTS,
        **PositionSizeAllInMixin.PARAM_CONSTRAINTS,
    }


class SLExtremumTPRiskRewardPSByRiskRiskManager(
    StopLossExtremumMixin,
    TakeProfitRiskRewardMixin,
    PositionSizeLimitMixin,
    PositionSizeByRiskMixin,
    AbstractRiskManager,
):
    """
    Риск-менеджер: стоп-лосс по экстремумам, тейк-профит по risk/reward, размер позиции по риску.
    """
    PARAM_CONSTRAINTS = {
        **StopLossExtremumMixin.PARAM_CONSTRAINTS,
        **TakeProfitRiskRewardMixin.PARAM_CONSTRAINTS,
        **PositionSizeLimitMixin.PARAM_CONSTRAINTS,
        **PositionSizeByRiskMixin.PARAM_CONSTRAINTS,
    }
