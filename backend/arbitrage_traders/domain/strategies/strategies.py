from decimal import Decimal
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

    Открывает LONG когда spread < 1 - open_threshold (первая биржа дешевле).
    Открывает SHORT когда spread > 1 + open_threshold (первая биржа дороже).
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
        """
        Args:
            open_threshold: Порог отклонения от 1.0 для открытия позиции.
            close_threshold: Порог отклонения от 1.0 для закрытия позиции.
        """
        if not isinstance(open_threshold, int | float):
            raise TypeError("open_threshold должен быть числом.")
        if not (self.OPEN_THRESHOLD_MIN <= open_threshold <= self.OPEN_THRESHOLD_MAX):
            raise ValueError(
                f"open_threshold должен быть в диапазоне [{self.OPEN_THRESHOLD_MIN}, {self.OPEN_THRESHOLD_MAX}]."
            )

        if not isinstance(close_threshold, int | float):
            raise TypeError("close_threshold должен быть числом.")
        if not (
            self.CLOSE_THRESHOLD_MIN <= close_threshold <= self.CLOSE_THRESHOLD_MAX
        ):
            raise ValueError(
                f"close_threshold должен быть в диапазоне [{self.CLOSE_THRESHOLD_MIN}, {self.CLOSE_THRESHOLD_MAX}]."
            )

        self.open_threshold = float(open_threshold)
        self.close_threshold = float(close_threshold)

    def get_signal(
        self,
        trader: "ArbitrageTrader",
        candle: ArbitrageCandle,
    ) -> ArbitrageTraderSignal:
        """
        Генерирует торговый сигнал на основе спреда между биржами.

        BUY (LONG): spread < 1 - open_threshold (первая биржа дешевле)
        SELL (SHORT): spread > 1 + open_threshold (первая биржа дороже)
        WAIT: 1 - open_threshold <= spread <= 1 + open_threshold
        """
        logger.debug(
            f"SpreadReversionArbitrageStrategy: обработка свечей "
            f"first={candle.left}, second={candle.right}"
        )

        try:
            spread = candle.spread
            price_first = float(candle.left.close)
            price_second = float(candle.right.close)
        except ValueError as e:
            logger.error(f"Ошибка расчета спреда: {e}")
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
            price_first=price_first,
            price_second=price_second,
        ).model_dump()

        left_type = SignalType.WAIT
        right_type = SignalType.WAIT

        # Покупаем когда первая биржа дешевле
        # BUY на первой бирже, SELL на второй
        if spread < 1 - self.open_threshold:
            left_type = SignalType.BUY
            right_type = SignalType.SELL
            logger.info(
                f"Сигнал BUY: спред {spread:.6f} < {1 - self.open_threshold:.6f} "
                f"(первая биржа дешевле)"
            )

        # Продаем когда первая биржа дороже
        # SELL на первой бирже, BUY на второй
        elif spread > 1 + self.open_threshold:
            left_type = SignalType.SELL
            right_type = SignalType.BUY
            logger.info(
                f"Сигнал SELL: спред {spread:.6f} > {1 + self.open_threshold:.6f} "
                f"(первая биржа дороже)"
            )

        return ArbitrageTraderSignal(
            timestamp=candle.timestamp,
            left_price=Decimal(str(price_first)),
            right_price=Decimal(str(price_second)),
            left_type=left_type,
            right_type=right_type,
            left_candle=candle.left,
            right_candle=candle.right,
            data=data,
        )

    def position_should_be_closed(
        self, signal: ArbitrageTraderSignal, position: "ArbitrageTraderPosition"
    ) -> bool:
        """
        Закрываем позицию когда спред возвращается к паритету:
        - LONG: когда spread >= 1 - close_threshold
        - SHORT: когда spread <= 1 + close_threshold
        """
        try:
            data = SpreadReversionArbitrageData(**signal.data)
            spread = data.spread
        except Exception:
            logger.warning("Не удалось получить данные о спреде из сигнала")
            return False

        # Для LONG позиции (купили на первой бирже)
        # Закрываем когда спред возвращается к паритету
        if position.left_type == PositionType.LONG:
            should_close = spread >= 1 - self.close_threshold
            if should_close:
                logger.info(
                    f"Закрытие LONG: спред {spread:.6f} >= "
                    f"{1 - self.close_threshold:.6f} (возврат к паритету)"
                )
            return should_close

        # Для SHORT позиции (продали на первой бирже)
        # Закрываем когда спред возвращается к паритету
        elif position.left_type == PositionType.SHORT:
            should_close = spread <= 1 + self.close_threshold
            if should_close:
                logger.info(
                    f"Закрытие SHORT: спред {spread:.6f} <= "
                    f"{1 + self.close_threshold:.6f} (возврат к паритету)"
                )
            return should_close

        return False


class CrossSpreadArbitrageStrategy(AbstractArbitrageStrategy):
    """
    Арбитражная стратегия с перекрёстным выходом через паритет.

    Спред = left / right (коэффициент, паритет = 1.0).

    Входит при отклонении спреда от 1.0, выходит когда спред переходит
    на противоположную сторону от паритета.

    Пример: open_threshold=0.004, close_threshold=0.004
    - Спред > 1.004 → SHORT (SELL left, BUY right)
      → закрытие когда спред <= 0.996
    - Спред < 0.996 → LONG (BUY left, SELL right)
      → закрытие когда спред >= 1.004
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
        """
        Генерирует торговый сигнал на основе спреда.

        BUY (LONG): spread < 1 - open_threshold (первая биржа дешевле)
        SELL (SHORT): spread > 1 + open_threshold (первая биржа дороже)
        WAIT: 1 - open_threshold <= spread <= 1 + open_threshold
        """
        try:
            spread = candle.spread
            price_first = float(candle.left.close)
            price_second = float(candle.right.close)
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
            price_first=price_first,
            price_second=price_second,
        ).model_dump()

        left_type = SignalType.WAIT
        right_type = SignalType.WAIT

        if spread < 1 - self.open_threshold:
            left_type = SignalType.BUY
            right_type = SignalType.SELL
            logger.info(
                f"CrossSpread BUY: спред {spread:.6f} < {1 - self.open_threshold:.6f}"
            )
        elif spread > 1 + self.open_threshold:
            left_type = SignalType.SELL
            right_type = SignalType.BUY
            logger.info(
                f"CrossSpread SELL: спред {spread:.6f} > {1 + self.open_threshold:.6f}"
            )

        return ArbitrageTraderSignal(
            timestamp=candle.timestamp,
            left_price=Decimal(str(price_first)),
            right_price=Decimal(str(price_second)),
            left_type=left_type,
            right_type=right_type,
            left_candle=candle.left,
            right_candle=candle.right,
            data=data,
        )

    def position_should_be_closed(
        self, signal: ArbitrageTraderSignal, position: "ArbitrageTraderPosition"
    ) -> bool:
        """
        Закрывает позицию когда спред переходит на противоположную сторону.

        LONG (вошли при spread < 1 - open_threshold):
            → закрываем когда spread >= 1 + close_threshold
        SHORT (вошли при spread > 1 + open_threshold):
            → закрываем когда spread <= 1 - close_threshold
        """
        try:
            data = CrossSpreadArbitrageData(**signal.data)
            spread = data.spread
        except Exception:
            logger.warning("Не удалось получить данные о спреде из сигнала")
            return False

        if position.left_type == PositionType.LONG:
            should_close = spread >= 1 + self.close_threshold
            if should_close:
                logger.info(
                    f"Закрытие LONG: спред {spread:.6f} >= "
                    f"{1 + self.close_threshold:.6f} (переход на другую сторону)"
                )
            return should_close

        elif position.left_type == PositionType.SHORT:
            should_close = spread <= 1 - self.close_threshold
            if should_close:
                logger.info(
                    f"Закрытие SHORT: спред {spread:.6f} <= "
                    f"{1 - self.close_threshold:.6f} (переход на другую сторону)"
                )
            return should_close

        return False
