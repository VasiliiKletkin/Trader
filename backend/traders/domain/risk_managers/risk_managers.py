from decimal import Decimal
from typing import TYPE_CHECKING

from loguru import logger

from ..schemas import PositionType
from .base import AbstractRiskManager, RiskManagerRegistry

if TYPE_CHECKING:
    from ..traders.traders import Trader


class StopLossPercentMixin:
    """
    Миксин: стоп-лосс по проценту от цены.
    """

    STOP_LOSS_PERCENT_MIN = 0.01
    STOP_LOSS_PERCENT_MAX = 30.0
    STOP_LOSS_PERCENT_DEFAULT = 1.0

    PARAM_CONSTRAINTS: dict[str, tuple[float, float]] = {
        "stop_loss_percent": (STOP_LOSS_PERCENT_MIN, STOP_LOSS_PERCENT_MAX)
    }

    def __init__(
        self, stop_loss_percent: float = STOP_LOSS_PERCENT_DEFAULT, *args, **kwargs
    ):
        """
        Инициализация миксина стоп-лосса по проценту.

        :param stop_loss_percent: Процент стоп-лосса от цены.
        """
        self.stop_loss_percent = Decimal(str(stop_loss_percent))
        if not (
            self.STOP_LOSS_PERCENT_MIN
            <= float(self.stop_loss_percent)
            <= self.STOP_LOSS_PERCENT_MAX
        ):
            raise ValueError(
                f"stop_loss_percent должен быть в диапазоне "
                f"[{self.STOP_LOSS_PERCENT_MIN}, {self.STOP_LOSS_PERCENT_MAX}]."
            )
        super().__init__(*args, **kwargs)

    def get_stop_loss(
        self, trader: "Trader", position_type: PositionType, price: Decimal
    ) -> Decimal | None:
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


class StopLossExtremumMixin:
    """
    Миксин: стоп-лосс по экстремумам (минимум/максимум) последних N свечей.
    """

    EXTREMUM_CANDLE_LENGTH_MIN = 1
    EXTREMUM_CANDLE_LENGTH_MAX = 100
    EXTREMUM_CANDLE_LENGTH_DEFAULT = 5

    PARAM_CONSTRAINTS: dict[str, tuple[float, float]] = {
        "extremum_candle_length": (
            EXTREMUM_CANDLE_LENGTH_MIN,
            EXTREMUM_CANDLE_LENGTH_MAX,
        )
    }

    def __init__(
        self,
        extremum_candle_length: int = EXTREMUM_CANDLE_LENGTH_DEFAULT,
        *args,
        **kwargs,
    ):
        """
        Инициализация миксина стоп-лосса по экстремумам.

        :param extremum_candle_length: Количество последних свечей для поиска экстремума.
        """
        if not isinstance(extremum_candle_length, int):
            raise TypeError("extremum_candle_length должен быть целым числом.")
        if not (
            self.EXTREMUM_CANDLE_LENGTH_MIN
            <= extremum_candle_length
            <= self.EXTREMUM_CANDLE_LENGTH_MAX
        ):
            raise ValueError(
                f"extremum_candle_length должен быть в диапазоне "
                f"[{self.EXTREMUM_CANDLE_LENGTH_MIN}, {self.EXTREMUM_CANDLE_LENGTH_MAX}]."
            )
        self.extremum_candle_length = extremum_candle_length
        super().__init__(*args, **kwargs)

    def get_stop_loss(
        self, trader: "Trader", position_type: PositionType, price: Decimal
    ) -> Decimal | None:
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
        candles = trader.get_last_candles(count=self.extremum_candle_length)
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

    TAKE_PROFIT_PERCENT_MIN = 0.01
    TAKE_PROFIT_PERCENT_MAX = 50.0
    TAKE_PROFIT_PERCENT_DEFAULT = 2.0

    PARAM_CONSTRAINTS: dict[str, tuple[float, float]] = {
        "take_profit_percent": (TAKE_PROFIT_PERCENT_MIN, TAKE_PROFIT_PERCENT_MAX)
    }

    def __init__(
        self, take_profit_percent: float = TAKE_PROFIT_PERCENT_DEFAULT, *args, **kwargs
    ):
        """
        Инициализация миксина тейк-профита по проценту.

        :param take_profit_percent: Процент тейк-профита.
        """
        if not isinstance(take_profit_percent, int | float):
            raise TypeError("take_profit_percent должен быть числом.")
        if not (
            self.TAKE_PROFIT_PERCENT_MIN
            <= take_profit_percent
            <= self.TAKE_PROFIT_PERCENT_MAX
        ):
            raise ValueError(
                f"take_profit_percent должен быть в диапазоне "
                f"[{self.TAKE_PROFIT_PERCENT_MIN}, {self.TAKE_PROFIT_PERCENT_MAX}]."
            )
        self.take_profit_percent = Decimal(str(take_profit_percent))
        super().__init__(*args, **kwargs)

    def get_take_profit(
        self, trader: "Trader", position_type: PositionType, price: Decimal
    ) -> Decimal | None:
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
    Миксин: тейк-профит по risk/reward.
    """

    REWARD_RISK_MIN = 0.01
    REWARD_RISK_MAX = 10.0
    REWARD_RISK_DEFAULT = 2.0

    PARAM_CONSTRAINTS: dict[str, tuple[float, float]] = {
        "reward_risk": (REWARD_RISK_MIN, REWARD_RISK_MAX)
    }

    def __init__(self, reward_risk: float = REWARD_RISK_DEFAULT, *args, **kwargs):
        """
        Инициализация миксина тейк-профита по risk/reward.

        :param reward_risk: Соотношение reward/risk.
        """
        self.reward_risk = Decimal(str(reward_risk))
        if not (
            self.REWARD_RISK_MIN <= float(self.reward_risk) <= self.REWARD_RISK_MAX
        ):
            raise ValueError(
                f"reward_risk должен быть в диапазоне "
                f"[{self.REWARD_RISK_MIN}, {self.REWARD_RISK_MAX}]."
            )
        super().__init__(*args, **kwargs)

    def get_take_profit(
        self, trader: "Trader", position_type: PositionType, price: Decimal
    ) -> Decimal | None:
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
        stop_loss = self.get_stop_loss(trader, position_type=position_type, price=price)  # type: ignore[attr-defined]
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
    Миксин: размер позиции — весь баланс (cost = balance).
    """

    PARAM_CONSTRAINTS: dict[str, tuple[float, float]] = {}

    def calculate_position_size(
        self,
        trader: "Trader",
        position_type: PositionType,
        price: Decimal,
        balance: Decimal,
    ) -> Decimal:
        """
        Возвращает cost позиции равный балансу.

        :return: cost в settle_currency.
        """
        logger.debug(
            f"PositionSizeAllInMixin.calculate_position_size: type={position_type}, price={price}, balance={balance}"
        )
        return balance


class PositionSizeByRiskMixin:
    """
    Миксин: размер позиции по риску и стоп-лоссу.
    """

    MAX_RISK_PER_TRADE_MIN = 0.1
    MAX_RISK_PER_TRADE_MAX = 100.0
    MAX_RISK_PER_TRADE_DEFAULT = 1.5

    PARAM_CONSTRAINTS: dict[str, tuple[float, float]] = {
        "max_risk_per_trade": (MAX_RISK_PER_TRADE_MIN, MAX_RISK_PER_TRADE_MAX)
    }

    def __init__(
        self, max_risk_per_trade: float = MAX_RISK_PER_TRADE_DEFAULT, *args, **kwargs
    ):
        """
        Инициализация миксина размера позиции по риску.

        :param max_risk_per_trade: Максимальный риск на сделку в процентах от баланса.
        """
        self.max_risk_per_trade = Decimal(str(max_risk_per_trade))
        if not (
            self.MAX_RISK_PER_TRADE_MIN
            <= float(self.max_risk_per_trade)
            <= self.MAX_RISK_PER_TRADE_MAX
        ):
            raise ValueError(
                f"max_risk_per_trade должен быть в диапазоне "
                f"[{self.MAX_RISK_PER_TRADE_MIN}, {self.MAX_RISK_PER_TRADE_MAX}]."
            )
        super().__init__(*args, **kwargs)

    def calculate_position_size(
        self,
        trader: "Trader",
        position_type: PositionType,
        price: Decimal,
        balance: Decimal,
    ) -> Decimal:
        """
        Рассчитывает cost позиции по риску на сделку.

        Формула: риск на сделку (в settle_currency) = balance * risk_fraction.
        Позиция такая, чтобы при срабатывании SL потеря равнялась риску:
        cost = risk_amount * price / stop_distance.
        :return: cost в settle_currency.
        """
        logger.debug(
            f"PositionSizeByRiskMixin.calculate_position_size: type={position_type}, price={price}, balance={balance}, risk={self.max_risk_per_trade}"
        )
        stop_loss = self.get_stop_loss(trader, position_type=position_type, price=price)  # type: ignore[attr-defined]
        if stop_loss is None:
            return Decimal("0.0")
        stop_distance = abs(price - stop_loss)
        if stop_distance == 0:
            return Decimal("0.0")
        risk_fraction = self.max_risk_per_trade / Decimal("100")
        risk_amount = balance * risk_fraction
        return risk_amount * price / stop_distance


class PositionSizeLimitMixin:
    """
    Миксин: ограничивает cost позиции балансом (defensive cap для ByRisk).
    """

    PARAM_CONSTRAINTS: dict[str, tuple[float, float]] = {}

    def calculate_position_size(
        self,
        trader: "Trader",
        position_type: PositionType,
        price: Decimal,
        balance: Decimal,
    ) -> Decimal:
        """
        Обрезает cost до размера баланса.
        """
        logger.debug(
            f"PositionSizeLimitMixin.calculate_position_size: type={position_type}, price={price}, balance={balance}"
        )
        cost = super().calculate_position_size(  # type: ignore[misc]
            trader, position_type=position_type, price=price, balance=balance
        )
        if cost > balance:
            return balance
        return cost


# --- Все вариации RiskManager ---


@RiskManagerRegistry.register
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

    PARAM_CONSTRAINTS: dict[str, tuple[float, float]] = {
        **StopLossPercentMixin.PARAM_CONSTRAINTS,
        **TakeProfitPercentMixin.PARAM_CONSTRAINTS,
        **PositionSizeLimitMixin.PARAM_CONSTRAINTS,
        **PositionSizeAllInMixin.PARAM_CONSTRAINTS,
    }


@RiskManagerRegistry.register
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

    PARAM_CONSTRAINTS: dict[str, tuple[float, float]] = {
        **StopLossPercentMixin.PARAM_CONSTRAINTS,
        **TakeProfitPercentMixin.PARAM_CONSTRAINTS,
        **PositionSizeLimitMixin.PARAM_CONSTRAINTS,
        **PositionSizeByRiskMixin.PARAM_CONSTRAINTS,
    }


@RiskManagerRegistry.register
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

    PARAM_CONSTRAINTS: dict[str, tuple[float, float]] = {
        **StopLossPercentMixin.PARAM_CONSTRAINTS,
        **TakeProfitRiskRewardMixin.PARAM_CONSTRAINTS,
        **PositionSizeLimitMixin.PARAM_CONSTRAINTS,
        **PositionSizeAllInMixin.PARAM_CONSTRAINTS,
    }


@RiskManagerRegistry.register
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

    PARAM_CONSTRAINTS: dict[str, tuple[float, float]] = {
        **StopLossPercentMixin.PARAM_CONSTRAINTS,
        **TakeProfitRiskRewardMixin.PARAM_CONSTRAINTS,
        **PositionSizeLimitMixin.PARAM_CONSTRAINTS,
        **PositionSizeByRiskMixin.PARAM_CONSTRAINTS,
    }


@RiskManagerRegistry.register
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

    PARAM_CONSTRAINTS: dict[str, tuple[float, float]] = {
        **StopLossExtremumMixin.PARAM_CONSTRAINTS,
        **TakeProfitPercentMixin.PARAM_CONSTRAINTS,
        **PositionSizeLimitMixin.PARAM_CONSTRAINTS,
        **PositionSizeAllInMixin.PARAM_CONSTRAINTS,
    }


@RiskManagerRegistry.register
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

    PARAM_CONSTRAINTS: dict[str, tuple[float, float]] = {
        **StopLossExtremumMixin.PARAM_CONSTRAINTS,
        **TakeProfitPercentMixin.PARAM_CONSTRAINTS,
        **PositionSizeLimitMixin.PARAM_CONSTRAINTS,
        **PositionSizeByRiskMixin.PARAM_CONSTRAINTS,
    }


@RiskManagerRegistry.register
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

    PARAM_CONSTRAINTS: dict[str, tuple[float, float]] = {
        **StopLossExtremumMixin.PARAM_CONSTRAINTS,
        **TakeProfitRiskRewardMixin.PARAM_CONSTRAINTS,
        **PositionSizeLimitMixin.PARAM_CONSTRAINTS,
        **PositionSizeAllInMixin.PARAM_CONSTRAINTS,
    }


@RiskManagerRegistry.register
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

    PARAM_CONSTRAINTS: dict[str, tuple[float, float]] = {
        **StopLossExtremumMixin.PARAM_CONSTRAINTS,
        **TakeProfitRiskRewardMixin.PARAM_CONSTRAINTS,
        **PositionSizeLimitMixin.PARAM_CONSTRAINTS,
        **PositionSizeByRiskMixin.PARAM_CONSTRAINTS,
    }
