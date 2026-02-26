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
    Арбитражная стратегия возврата спреда к нулю.

    Открывает LONG когда спред < -open_threshold (первая биржа дешевле).
    Открывает SHORT когда спред > +open_threshold (первая биржа дороже).
    Закрывает позицию когда спред возвращается к close_threshold.

    Спред = (price_left - price_right) / price_right * 100
    """

    OPEN_THRESHOLD_MIN = 0.1
    OPEN_THRESHOLD_MAX = 10.0
    OPEN_THRESHOLD_DEFAULT = 1.0

    CLOSE_THRESHOLD_MIN = 0.0
    CLOSE_THRESHOLD_MAX = 5.0
    CLOSE_THRESHOLD_DEFAULT = 0.2

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
        Инициализация простой арбитражной стратегии.

        Args:
            open_threshold: Порог спреда для открытия позиции (%). Открываем когда |спред| > open_threshold
            close_threshold: Порог для закрытия позиции (%). Закрываем когда |спред| < close_threshold
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

        BUY (LONG): открываем позицию когда spread < -open_threshold (первая биржа дешевле)
        SELL (SHORT): открываем позицию когда spread > open_threshold (первая биржа дороже)
        WAIT: когда |spread| <= open_threshold
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

        # Покупаем когда первая биржа дешевле (отрицательный спред)
        # BUY на первой бирже, SELL на второй
        if spread < -self.open_threshold:
            left_type = SignalType.BUY
            right_type = SignalType.SELL
            logger.info(
                f"Сигнал BUY: спред {spread:.4f}% < -{self.open_threshold}% "
                f"(первая биржа дешевле)"
            )

        # Продаем когда первая биржа дороже (положительный спред)
        # SELL на первой бирже, BUY на второй
        elif spread > self.open_threshold:
            left_type = SignalType.SELL
            right_type = SignalType.BUY
            logger.info(
                f"Сигнал SELL: спред {spread:.4f}% > {self.open_threshold}% "
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
        Определяет, нужно ли закрыть позицию на основе текущего спреда.

        Закрываем позицию когда спред возвращается к close_threshold:
        - Для LONG позиции: когда спред становится >= -close_threshold
        - Для SHORT позиции: когда спред становится <= close_threshold

        Args:
            signal: Текущий сигнал
            position: Открытая позиция

        Returns:
            True если позицию нужно закрыть
        """
        try:
            data = SpreadReversionArbitrageData(**signal.data)
            spread = data.spread
        except Exception:
            logger.warning("Не удалось получить данные о спреде из сигнала")
            return False

        # Для LONG позиции (купили на первой бирже)
        # Закрываем когда спред возвращается к нулю или становится положительным
        if position.type == PositionType.LONG:
            should_close = spread >= -self.close_threshold
            if should_close:
                logger.info(
                    f"Закрытие LONG позиции: спред {spread:.4f}% >= "
                    f"-{self.close_threshold}% (возврат к балансу)"
                )
            return should_close

        # Для SHORT позиции (продали на первой бирже)
        # Закрываем когда спред возвращается к нулю или становится отрицательным
        elif position.type == PositionType.SHORT:
            should_close = spread <= self.close_threshold
            if should_close:
                logger.info(
                    f"Закрытие SHORT позиции: спред {spread:.4f}% <= "
                    f"{self.close_threshold}% (возврат к балансу)"
                )
            return should_close

        return False


class CrossSpreadArbitrageStrategy(AbstractArbitrageStrategy):
    """
    Арбитражная стратегия с перекрёстным выходом через ноль.

    Входит при спреде на одной стороне, выходит когда спред переходит
    на противоположную сторону. Подходит для малых амплитуд колебаний спреда.

    Пример: open_threshold=0.4, close_threshold=0.4
    - Спред > +0.4% → SHORT (SELL left, BUY right)
      → закрытие когда спред <= -0.4%
    - Спред < -0.4% → LONG (BUY left, SELL right)
      → закрытие когда спред >= +0.4%

    Спред = (price_left - price_right) / price_right * 100
    """

    OPEN_THRESHOLD_MIN = 0.05
    OPEN_THRESHOLD_MAX = 10.0
    OPEN_THRESHOLD_DEFAULT = 0.4

    CLOSE_THRESHOLD_MIN = 0.05
    CLOSE_THRESHOLD_MAX = 10.0
    CLOSE_THRESHOLD_DEFAULT = 0.4

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

        BUY (LONG): spread < -open_threshold (первая биржа дешевле)
        SELL (SHORT): spread > +open_threshold (первая биржа дороже)
        WAIT: |spread| <= open_threshold
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

        if spread < -self.open_threshold:
            left_type = SignalType.BUY
            right_type = SignalType.SELL
            logger.info(
                f"CrossSpread BUY: спред {spread:.4f}% < -{self.open_threshold}%"
            )
        elif spread > self.open_threshold:
            left_type = SignalType.SELL
            right_type = SignalType.BUY
            logger.info(
                f"CrossSpread SELL: спред {spread:.4f}% > +{self.open_threshold}%"
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

        LONG (вошли при спреде < -open_threshold):
            → закрываем когда spread >= +close_threshold
        SHORT (вошли при спреде > +open_threshold):
            → закрываем когда spread <= -close_threshold
        """
        try:
            data = CrossSpreadArbitrageData(**signal.data)
            spread = data.spread
        except Exception:
            logger.warning("Не удалось получить данные о спреде из сигнала")
            return False

        if position.type == PositionType.LONG:
            should_close = spread >= self.close_threshold
            if should_close:
                logger.info(
                    f"Закрытие LONG: спред {spread:.4f}% >= "
                    f"+{self.close_threshold}% (переход на другую сторону)"
                )
            return should_close

        elif position.type == PositionType.SHORT:
            should_close = spread <= -self.close_threshold
            if should_close:
                logger.info(
                    f"Закрытие SHORT: спред {spread:.4f}% <= "
                    f"-{self.close_threshold}% (переход на другую сторону)"
                )
            return should_close

        return False
