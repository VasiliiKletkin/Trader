from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from loguru import logger

from .base import AbstractRiskManager
from .schemas import PositionType

if TYPE_CHECKING:
    from traders.domain import Trader


class StopLossPercentMixin:
    """
    Миксин: стоп-лосс по проценту от цены.
    """

    PARAM_CONSTRAINTS = {'stop_loss_percent': (0.01, 30.0)}

    def __init__(self, stop_loss_percent: float = 1.0, *args, **kwargs):
        """
        Инициализация миксина стоп-лосса по проценту.

        :param stop_loss_percent: Процент стоп-лосса от цены (0.01 - 30.0).
        """
        self.stop_loss_percent = Decimal(str(stop_loss_percent))
        if not (0.01 <= float(self.stop_loss_percent) <= 30.0):
            raise ValueError("stop_loss_percent должен быть в диапазоне [0.01, 30.0].")
        super().__init__(*args, **kwargs)

    def get_stop_loss(
        self, trader: "Trader", position_type: PositionType, price: Decimal
    ) -> Optional[Decimal]:
        """
        Рассчитывает стоп-лосс по проценту от цены.

        :param trader: Экземпляр трейдера.
        :param position_type: Тип позиции (LONG/SHORT).
        :param price: Текущая цена.
        :return: Цена стоп-лосса или None.
        """
        logger.debug(
            f"StopLossPercentMixin.get_stop_loss: type={position_type}, price={price}, percent={self.stop_loss_percent}"
        )
        if position_type == PositionType.LONG:
            stop_loss = price - (price * self.stop_loss_percent / Decimal("100"))
        elif position_type == PositionType.SHORT:
            stop_loss = price + (price * self.stop_loss_percent / Decimal("100"))
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
        Инициализация миксина стоп-лосса по Renko.

        :param trashold_up: Процент для стоп-лосса при SHORT (>= 0, <= 100).
        :param trashold_down: Процент для стоп-лосса при LONG (>= 0, <= 100).
        """
        self.trashold_up = Decimal(str(trashold_up))
        self.trashold_down = Decimal(str(trashold_down))
        if not (0.0 <= float(self.trashold_up) <= 100.0) or not (0.0 <= float(self.trashold_down) <= 100.0):
            raise ValueError("trashold_up и trashold_down должны быть в диапазоне [0, 100].")
        super().__init__(*args, **kwargs)

    def get_stop_loss(
        self, trader: "Trader", position_type: PositionType, price: Decimal
    ) -> Optional[Decimal]:
        """
        Рассчитывает стоп-лосс по Renko-порогам.

        :param trader: Экземпляр трейдера.
        :param position_type: Тип позиции (LONG/SHORT).
        :param price: Текущая цена.
        :return: Цена стоп-лосса или None.
        """
        logger.debug(
            f"StopLossRenkoMixin.get_stop_loss: type={position_type}, price={price}, up={self.trashold_up}, down={self.trashold_down}"
        )
        if position_type == PositionType.LONG:
            stop_loss = price - (price * self.trashold_down / Decimal("100"))
        elif position_type == PositionType.SHORT:
            stop_loss = price + (price * self.trashold_up / Decimal("100"))
        return stop_loss


class StopLossExtremumMixin:
    """
    Миксин: стоп-лосс по экстремумам (минимум/максимум) последних N свечей.
    """

    PARAM_CONSTRAINTS = {'extremum_candle_length': (1, 100)}

    def __init__(self, extremum_candle_length: int = 5, *args, **kwargs):
        """
        Инициализация миксина стоп-лосса по экстремумам.

        :param extremum_candle_length: Количество последних свечей для поиска экстремума (1-100).
        """
        if not isinstance(extremum_candle_length, int):
            raise TypeError("extremum_candle_length должен быть целым числом.")
        if not (1 <= extremum_candle_length <= 100):
            raise ValueError("extremum_candle_length должен быть в диапазоне [1, 100].")
        self.extremum_candle_length = extremum_candle_length
        super().__init__(*args, **kwargs)

    def get_stop_loss(
        self, trader: "Trader", position_type: PositionType, price: Decimal
    ) -> Optional[Decimal]:
        """
        Рассчитывает стоп-лосс по экстремумам последних свечей.

        :param trader: Экземпляр трейдера.
        :param position_type: Тип позиции (LONG/SHORT).
        :param price: Текущая цена.
        :return: Цена стоп-лосса или None.
        """
        logger.debug(
            f"StopLossExtremumMixin.get_stop_loss: type={position_type}, price={price}, length={self.extremum_candle_length}"
        )
        candles = trader.candles[-self.extremum_candle_length:] if trader.candles else []
        if not candles:
            return None
        if position_type == PositionType.LONG:
            stop_loss = min(c.low for c in candles)
        elif position_type == PositionType.SHORT:
            stop_loss = max(c.high for c in candles)
        return stop_loss


class TakeProfitPercentMixin:
    """
    Миксин: тейк-профит в процентах от цены открытия.
    """

    PARAM_CONSTRAINTS = {'take_profit_percent': (0.01, 50.0)}

    def __init__(self, take_profit_percent: float = 2.0, *args, **kwargs):
        """
        Инициализация миксина тейк-профита по проценту.

        :param take_profit_percent: Процент тейк-профита (0.01 - 50.0).
        """
        if not isinstance(take_profit_percent, (int, float)):
            raise TypeError("take_profit_percent должен быть числом.")
        if not (0.01 <= take_profit_percent <= 50.0):
            raise ValueError("take_profit_percent должен быть в отрезке [0.01, 50.0].")
        self.take_profit_percent = Decimal(str(take_profit_percent))
        super().__init__(*args, **kwargs)

    def get_take_profit(
        self, trader: "Trader", position_type: PositionType, price: Decimal
    ) -> Optional[Decimal]:
        """
        Рассчитывает тейк-профит по проценту от цены.

        :param trader: Экземпляр трейдера.
        :param position_type: Тип позиции (LONG/SHORT).
        :param price: Текущая цена.
        :return: Цена тейк-профита или None.
        """
        logger.debug(
            f"TakeProfitPercentMixin.get_take_profit: type={position_type}, price={price}, percent={self.take_profit_percent}"
        )
        if position_type == PositionType.LONG:
            take_profit = price + (price * self.take_profit_percent / Decimal("100"))
        elif position_type == PositionType.SHORT:
            take_profit = price - (price * self.take_profit_percent / Decimal("100"))
        return take_profit


class TakeProfitRiskRewardMixin:
    """
    Миксин: тейк-профит по risk/reward (Renko).
    """

    PARAM_CONSTRAINTS = {'reward_risk': (0.01, 10.0)}

    def __init__(self, reward_risk: float = 2.0, *args, **kwargs):
        """
        Инициализация миксина тейк-профита по risk/reward.

        :param reward_risk: Соотношение reward/risk (0.01 - 10.0).
        """
        self.reward_risk = Decimal(str(reward_risk))
        if not (0.01 <= float(self.reward_risk) <= 10.0):
            raise ValueError("reward_risk должен быть в диапазоне [0.01, 10.0].")
        super().__init__(*args, **kwargs)

    def get_take_profit(
        self, trader: "Trader", position_type: PositionType, price: Decimal
    ) -> Optional[Decimal]:
        """
        Рассчитывает тейк-профит по risk/reward.

        :param trader: Экземпляр трейдера.
        :param position_type: Тип позиции (LONG/SHORT).
        :param price: Текущая цена.
        :return: Цена тейк-профита или None.
        """
        logger.debug(
            f"TakeProfitRiskRewardMixin.get_take_profit: type={position_type}, price={price}, reward_risk={self.reward_risk}"
        )
        stop_loss = self.get_stop_loss(trader, position_type=position_type, price=price)
        if stop_loss is None or not self.reward_risk:
            return None
        risk_distance = abs(price - stop_loss)
        reward_distance = risk_distance * self.reward_risk
        if position_type == PositionType.LONG:
            take_profit = price + reward_distance
        elif position_type == PositionType.SHORT:
            take_profit = price - reward_distance
        return take_profit


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
        """
        Рассчитывает размер позиции как весь баланс.

        :param trader: Экземпляр трейдера.
        :param position_type: Тип позиции (LONG/SHORT).
        :param price: Текущая цена.
        :param balance: Текущий баланс.
        :return: Размер позиции.
        """
        logger.debug(
            f"PositionSizeAllInMixin.calculate_position_size: type={position_type}, price={price}, balance={balance}"
        )
        size = balance / price
        return size


class PositionSizeByRiskMixin:
    """
    Миксин: размер позиции по риску и стоп-лоссу.
    """

    PARAM_CONSTRAINTS = {'max_risk_per_trade': (0.1, 100.0)}

    def __init__(self, max_risk_per_trade: float = 1.5, *args, **kwargs):
        """
        Инициализация миксина размера позиции по риску.

        :param max_risk_per_trade: Максимальный риск на сделку в процентах от баланса (0.1 - 100.0).
        """
        self.max_risk_per_trade = Decimal(str(max_risk_per_trade))
        if not (0.1 <= float(self.max_risk_per_trade) <= 100.0):
            raise ValueError("max_risk_per_trade должен быть в диапазоне (0.1, 100].")
        super().__init__(*args, **kwargs)

    def calculate_position_size(
        self,
        trader: "Trader",
        position_type: PositionType,
        price: Decimal,
        balance: Decimal,
    ) -> Decimal:
        """
        Рассчитывает размер позиции по риску.

        :param trader: Экземпляр трейдера.
        :param position_type: Тип позиции (LONG/SHORT).
        :param price: Текущая цена.
        :param balance: Текущий баланс.
        :return: Размер позиции.
        """
        logger.debug(
            f"PositionSizeByRiskMixin.calculate_position_size: type={position_type}, price={price}, balance={balance}, risk={self.max_risk_per_trade}"
        )
        stop_loss = self.get_stop_loss(trader, position_type=position_type, price=price)
        if stop_loss is None:
            return Decimal("0.0")
        stop_distance = abs(price - stop_loss)
        if stop_distance == 0:
            return Decimal("0.0")
        risk_fraction = self.max_risk_per_trade / Decimal("100")
        risk_amount = balance * risk_fraction
        position_size = risk_amount / stop_distance
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
        """
        Рассчитывает и ограничивает размер позиции.

        :param trader: Экземпляр трейдера.
        :param position_type: Тип позиции (LONG/SHORT).
        :param price: Текущая цена.
        :param balance: Текущий баланс.
        :return: Ограниченный размер позиции.
        """
        logger.debug(
            f"PositionSizeLimitMixin.calculate_position_size: type={position_type}, price={price}, balance={balance}"
        )
        size = super().calculate_position_size(
            trader, position_type=position_type, price=price, balance=balance
        )
        if price <= 0:
            return Decimal("0.0")
        max_size = balance / price
        if size > max_size:
            return max_size
        return size


# --- Все вариации RiskManager ---

# (Оставлены без изменений, так как они просто комбинируют миксины)
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
