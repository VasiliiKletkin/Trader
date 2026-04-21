from decimal import Decimal
from typing import TYPE_CHECKING

from loguru import logger

from arbitrage_traders.domain.schemas import PositionType

from .base import AbstractArbitrageRiskManager, ArbitrageRiskManagerRegistry

if TYPE_CHECKING:
    from arbitrage_traders.domain.traders import ArbitrageTrader


class PositionSizeAllInMixin:
    """Миксин: cost позиции = весь баланс."""

    PARAM_CONSTRAINTS: dict[str, tuple[float, float]] = {}

    def calculate_position_size(
        self,
        trader: "ArbitrageTrader",
        position_type: PositionType,
        price: Decimal,
        balance: Decimal,
    ) -> Decimal:
        logger.debug(
            f"PositionSizeAllInMixin.calculate_position_size: "
            f"type={position_type}, price={price}, balance={balance}"
        )
        return balance


class PositionSizePercentMixin:
    """Миксин: cost позиции как процент от баланса."""

    POSITION_SIZE_PERCENT_MIN = 0.1
    POSITION_SIZE_PERCENT_MAX = 100.0
    POSITION_SIZE_PERCENT_DEFAULT = 100.0

    PARAM_CONSTRAINTS: dict[str, tuple[float, float]] = {
        "position_size_percent": (
            POSITION_SIZE_PERCENT_MIN,
            POSITION_SIZE_PERCENT_MAX,
        )
    }

    def __init__(
        self,
        position_size_percent: float = POSITION_SIZE_PERCENT_DEFAULT,
        *args,
        **kwargs,
    ):
        self.position_size_percent = Decimal(str(position_size_percent))
        if not (
            self.POSITION_SIZE_PERCENT_MIN
            <= float(self.position_size_percent)
            <= self.POSITION_SIZE_PERCENT_MAX
        ):
            raise ValueError(
                f"position_size_percent должен быть в диапазоне "
                f"[{self.POSITION_SIZE_PERCENT_MIN}, {self.POSITION_SIZE_PERCENT_MAX}]."
            )
        super().__init__(*args, **kwargs)

    def calculate_position_size(
        self,
        trader: "ArbitrageTrader",
        position_type: PositionType,
        price: Decimal,
        balance: Decimal,
    ) -> Decimal:
        logger.debug(
            f"PositionSizePercentMixin.calculate_position_size: type={position_type}, "
            f"price={price}, balance={balance}, percent={self.position_size_percent}"
        )
        return balance * self.position_size_percent / Decimal("100")


@ArbitrageRiskManagerRegistry.register
class PSAllInArbitrageRiskManager(PositionSizeAllInMixin, AbstractArbitrageRiskManager):
    """Арбитражный риск-менеджер: весь баланс."""

    PARAM_CONSTRAINTS: dict[str, tuple[float, float]] = {
        **PositionSizeAllInMixin.PARAM_CONSTRAINTS
    }


@ArbitrageRiskManagerRegistry.register
class PSPercentArbitrageRiskManager(
    PositionSizePercentMixin, AbstractArbitrageRiskManager
):
    """Арбитражный риск-менеджер: размер позиции по проценту от баланса."""

    PARAM_CONSTRAINTS: dict[str, tuple[float, float]] = {
        **PositionSizePercentMixin.PARAM_CONSTRAINTS
    }
