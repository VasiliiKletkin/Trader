from abc import ABC, abstractmethod
from decimal import Decimal
from typing import TYPE_CHECKING

from arbitrage_traders.domain.schemas import PositionType
from core.utils.registry import Registry

if TYPE_CHECKING:
    from arbitrage_traders.domain.traders import ArbitrageTrader


class ArbitrageRiskManagerRegistry(Registry):
    pass


class AbstractArbitrageRiskManager(ABC):
    """
    Абстрактный базовый класс для арбитражного Risk Manager.
    Отвечает только за расчёт размера позиции (без стоп-лосса и тейк-профита).
    """

    PARAM_CONSTRAINTS: dict[str, tuple[float, float]] = {}

    @abstractmethod
    def calculate_position_size(
        self,
        trader: "ArbitrageTrader",
        position_type: PositionType,
        price: Decimal,
        balance: Decimal,
    ) -> Decimal:
        pass
