from typing import TYPE_CHECKING

from loguru import logger

from arbitrage_traders.domain.schemas import ArbitrageCandle, PositionType, SignalType

from ..schemas import (
    ArbitrageTraderSignal,
    CrossSpreadArbitrageData,
    SpreadReversionArbitrageData,
)
from .base import AbstractArbitrageStrategy

if TYPE_CHECKING:
    from arbitrage_traders.domain.schemas import ArbitrageTraderPosition
    from arbitrage_traders.domain.traders import ArbitrageTrader


class SpreadReversionArbitrageStrategy(AbstractArbitrageStrategy):
    """
    Арбитражная стратегия возврата спреда к паритету.

    Спред = left / right (коэффициент, паритет = 1.0).

    Открывает LONG когда spread < 1 - open_threshold (левая биржа дешевле).
    Открывает SHORT когда spread > 1 + open_threshold (левая биржа дороже).
    Закрывает позицию когда спред возвращается к 1 ± close_threshold.
    """

    OPEN_THRESHOLD_MIN = 0.0
    OPEN_THRESHOLD_MAX = 0.1
    OPEN_THRESHOLD_DEFAULT = 0.05

    CLOSE_THRESHOLD_MIN = 0.0
    CLOSE_THRESHOLD_MAX = 0.05
    CLOSE_THRESHOLD_DEFAULT = 0.01

    PARAM_CONSTRAINTS = {
        "open_threshold": (OPEN_THRESHOLD_MIN, OPEN_THRESHOLD_MAX),
        "close_threshold": (CLOSE_THRESHOLD_MIN, CLOSE_THRESHOLD_MAX),
    }

    def __init__(
        self,
        open_threshold: float = OPEN_THRESHOLD_DEFAULT,
        close_threshold: float = CLOSE_THRESHOLD_DEFAULT,
    ):
        if not isinstance(open_threshold, int | float):
            raise TypeError("open_threshold должен быть числом.")
        if not (self.OPEN_THRESHOLD_MIN <= open_threshold <= self.OPEN_THRESHOLD_MAX):
            raise ValueError(
                f"open_threshold должен быть в диапазоне "
                f"[{self.OPEN_THRESHOLD_MIN}, {self.OPEN_THRESHOLD_MAX}]."
            )
        if not isinstance(close_threshold, int | float):
            raise TypeError("close_threshold должен быть числом.")
        if not (
            self.CLOSE_THRESHOLD_MIN <= close_threshold <= self.CLOSE_THRESHOLD_MAX
        ):
            raise ValueError(
                f"close_threshold должен быть в диапазоне "
                f"[{self.CLOSE_THRESHOLD_MIN}, {self.CLOSE_THRESHOLD_MAX}]."
            )
        self.open_threshold = float(open_threshold)
        self.close_threshold = float(close_threshold)

    def get_signal(
        self,
        trader: "ArbitrageTrader",
        candle: ArbitrageCandle,
    ) -> ArbitrageTraderSignal:
        try:
            spread = candle.spread
        except ValueError as e:
            logger.error(f"Ошибка расчёта спреда: {e}")
            return ArbitrageTraderSignal(
                timestamp=candle.timestamp,
                left_price=candle.left.close,
                right_price=candle.right.close,
                left_type=SignalType.WAIT,
                right_type=SignalType.WAIT,
                left_candle=candle.left,
                right_candle=candle.right,
                data={},
            )

        data = SpreadReversionArbitrageData(
            spread=spread,
            left_price=float(candle.left.close),
            right_price=float(candle.right.close),
        ).model_dump()

        left_type = SignalType.WAIT
        right_type = SignalType.WAIT

        if spread < 1 - self.open_threshold:
            left_type = SignalType.BUY
            right_type = SignalType.SELL
        elif spread > 1 + self.open_threshold:
            left_type = SignalType.SELL
            right_type = SignalType.BUY

        return ArbitrageTraderSignal(
            timestamp=candle.timestamp,
            left_price=candle.left.close,
            right_price=candle.right.close,
            left_type=left_type,
            right_type=right_type,
            left_candle=candle.left,
            right_candle=candle.right,
            data=data,
        )

    def position_should_be_closed(
        self, signal: ArbitrageTraderSignal, position: "ArbitrageTraderPosition"
    ) -> bool:
        try:
            spread = SpreadReversionArbitrageData(**signal.data).spread
        except Exception:
            return False

        if position.left_type == PositionType.LONG:
            return spread >= 1 - self.close_threshold
        elif position.left_type == PositionType.SHORT:
            return spread <= 1 + self.close_threshold
        return False


class CrossSpreadArbitrageStrategy(AbstractArbitrageStrategy):
    """
    Арбитражная стратегия с перекрёстным выходом через паритет.

    Спред = left / right (коэффициент, паритет = 1.0).

    Входит при отклонении спреда от 1.0, выходит когда спред переходит
    на противоположную сторону от паритета.
    """

    OPEN_THRESHOLD_MIN = 0.0
    OPEN_THRESHOLD_MAX = 0.1
    OPEN_THRESHOLD_DEFAULT = 0.05

    CLOSE_THRESHOLD_MIN = 0.0
    CLOSE_THRESHOLD_MAX = 0.1
    CLOSE_THRESHOLD_DEFAULT = 0.05

    PARAM_CONSTRAINTS = {
        "open_threshold": (OPEN_THRESHOLD_MIN, OPEN_THRESHOLD_MAX),
        "close_threshold": (CLOSE_THRESHOLD_MIN, CLOSE_THRESHOLD_MAX),
    }

    def __init__(
        self,
        open_threshold: float = OPEN_THRESHOLD_DEFAULT,
        close_threshold: float = CLOSE_THRESHOLD_DEFAULT,
    ):
        if not isinstance(open_threshold, int | float):
            raise TypeError("open_threshold должен быть числом.")
        if not (self.OPEN_THRESHOLD_MIN <= open_threshold <= self.OPEN_THRESHOLD_MAX):
            raise ValueError(
                f"open_threshold должен быть в диапазоне "
                f"[{self.OPEN_THRESHOLD_MIN}, {self.OPEN_THRESHOLD_MAX}]."
            )
        if not isinstance(close_threshold, int | float):
            raise TypeError("close_threshold должен быть числом.")
        if not (
            self.CLOSE_THRESHOLD_MIN <= close_threshold <= self.CLOSE_THRESHOLD_MAX
        ):
            raise ValueError(
                f"close_threshold должен быть в диапазоне "
                f"[{self.CLOSE_THRESHOLD_MIN}, {self.CLOSE_THRESHOLD_MAX}]."
            )
        self.open_threshold = float(open_threshold)
        self.close_threshold = float(close_threshold)

    def get_signal(
        self,
        trader: "ArbitrageTrader",
        candle: ArbitrageCandle,
    ) -> ArbitrageTraderSignal:
        try:
            spread = candle.spread
        except ValueError as e:
            logger.error(f"Ошибка расчёта спреда: {e}")
            return ArbitrageTraderSignal(
                timestamp=candle.timestamp,
                left_price=candle.left.close,
                right_price=candle.right.close,
                left_type=SignalType.WAIT,
                right_type=SignalType.WAIT,
                left_candle=candle.left,
                right_candle=candle.right,
                data={},
            )

        data = CrossSpreadArbitrageData(
            spread=spread,
            left_price=float(candle.left.close),
            right_price=float(candle.right.close),
        ).model_dump()

        left_type = SignalType.WAIT
        right_type = SignalType.WAIT

        if spread < 1 - self.open_threshold:
            left_type = SignalType.BUY
            right_type = SignalType.SELL
        elif spread > 1 + self.open_threshold:
            left_type = SignalType.SELL
            right_type = SignalType.BUY

        return ArbitrageTraderSignal(
            timestamp=candle.timestamp,
            left_price=candle.left.close,
            right_price=candle.right.close,
            left_type=left_type,
            right_type=right_type,
            left_candle=candle.left,
            right_candle=candle.right,
            data=data,
        )

    def position_should_be_closed(
        self, signal: ArbitrageTraderSignal, position: "ArbitrageTraderPosition"
    ) -> bool:
        try:
            spread = CrossSpreadArbitrageData(**signal.data).spread
        except Exception:
            return False

        if position.left_type == PositionType.LONG:
            return spread >= 1 + self.close_threshold
        elif position.left_type == PositionType.SHORT:
            return spread <= 1 - self.close_threshold
        return False
