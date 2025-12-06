from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

import pandas as pd
import pandas_ta as ta
from collections import deque
from typing import Dict, Optional, Tuple, List


from exchanges.domain import Candle
from loguru import logger
from risk_managers.domain import PositionType

from .base import AbstractStrategy
from .schemas import (
    MFIData,
    RenkoBrick,
    RenkoData,
    SignalType,
    StochasticData,
    TraderSignal,
    DonchianCrossoverData,
    MovingAverageCrossoverData,
    GridTradingData,
)

if TYPE_CHECKING:
    from traders.domain import Trader, TraderPosition


class RenkoStrategy(AbstractStrategy):
    """
    Реализация торговой стратегии на основе Renko-графиков.
    """

    PARAM_CONSTRAINTS = {
        "threshold_up": (0.1, 10.0),
        "threshold_down": (0.1, 10.0),
        "count_bricks": (1, 10),
    }

    def __init__(
        self,
        threshold_up: float = 1.0,
        threshold_down: float = 1.0,
        count_bricks: int = 3,
    ) -> None:
        """
        Инициализация RenkoStrategy.

        Args:
            threshold_up (float): Процент для кирпича вверх. По умолчанию 1.0.
            threshold_down (float): Процент для кирпича вниз. По умолчанию 1.0.
            count_bricks (int): Количество кирпичей для сигнала. По умолчанию 3.
        """
        self.threshold_up = threshold_up
        self.threshold_down = threshold_down
        self.count_bricks = count_bricks
        self._low_wick: Optional[Decimal] = None
        self._high_wick: Optional[Decimal] = None

        logger.info(
            f"RenkoStrategy инициализирована: threshold_up={threshold_up}, threshold_down={threshold_down}"
        )

    def get_signal(self, trader: "Trader", candle: Candle) -> TraderSignal:
        """
        Возвращает сигнал на основе кирпичей.

        Args:
            trader (Trader): Экземпляр трейдера.
            candle (Candle): Текущая свеча.

        Returns:
            TraderSignal: Торговый сигнал.
        """
        logger.debug(f"Обработка свечи: {candle}")
        new_bricks = self.build_bricks(candle, trader)
        bricks = [signal.data for signal in trader.signals] + new_bricks

        if len(bricks) < self.count_bricks:
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                price=candle.close,
                data=RenkoData(bricks=new_bricks).model_dump(),
            )

        last_bricks: List[RenkoBrick] = bricks[-self.count_bricks :]

        if all(brick.type == "up" for brick in last_bricks):
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.BUY,
                price=candle.close,
                data=RenkoData(bricks=new_bricks).model_dump(),
            )
        elif all(brick.type == "down" for brick in last_bricks):
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.SELL,
                price=candle.close,
                data=RenkoData(bricks=new_bricks).model_dump(),
            )
        else:
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                price=candle.close,
                data=RenkoData(bricks=new_bricks).model_dump(),
            )

    def _update_wick_min(self, wick: Optional[Decimal], price: Decimal) -> Decimal:
        return price if wick is None else min(wick, price)

    def _update_wick_max(self, wick: Optional[Decimal], price: Decimal) -> Decimal:
        return price if wick is None else max(wick, price)

    def build_bricks(self, candle: Candle, trader: "Trader") -> List[RenkoBrick]:
        """
        Строит кирпичи.

        Args:
            candle (Candle): Текущая свеча.
            trader (Trader): Экземпляр трейдера.

        Returns:
            List[RenkoBrick]: Список кирпичей.
        """
        price = candle.close
        dt = candle.timestamp
        new_bricks = []

        brick_size_up = price / Decimal("100") * Decimal(self.threshold_up)
        brick_size_down = price / Decimal("100") * Decimal(self.threshold_down)

        last = (
            None  # if trader.signals[-1].data["bricks"] if trader.signals else None FIM
        )

        if last is None:
            logger.debug("Первый кирпич строится.")
            brick = RenkoBrick(timestamp=dt, type="first", open=price, close=price)
            self.bricks.append(brick)
            return [brick]

        def create(
            direction: str, count: int, wick: Optional[Decimal] = None
        ) -> List[RenkoBrick]:
            size = brick_size_up if direction == "up" else brick_size_down
            logger.debug(f"Создаем {count} кирпичей в направлении {direction}.")
            bricks = self.create_bricks(dt, direction, count, size, wick)
            self._low_wick = None
            self._high_wick = None
            return bricks

        if last.type == "up":
            if price > last.close:
                count = int((price - last.close) / brick_size_up)
                if count > 0:
                    new_bricks = create("up", count, self._low_wick)
                else:
                    self._high_wick = self._update_wick_max(self._high_wick, price)
            elif price < last.open:
                count = int((last.open - price) / brick_size_down)
                if count > 0:
                    new_bricks = create("down", count, self._high_wick)
                else:
                    self._low_wick = self._update_wick_min(self._low_wick, price)

        elif last.type == "down":
            if price < last.close:
                count = int((last.close - price) / brick_size_down)
                if count > 0:
                    new_bricks = create("down", count, self._high_wick)
                else:
                    self._low_wick = self._update_wick_min(self._low_wick, price)
            elif price > last.open:
                count = int((price - last.open) / brick_size_up)
                if count > 0:
                    new_bricks = create("up", count, self._low_wick)
                else:
                    self._high_wick = self._update_wick_max(self._high_wick, price)

        elif last.type == "first":
            if price > last.close:
                count = int((price - last.close) / brick_size_up)
                if count > 0:
                    new_bricks = create("up", count)
            elif price < last.close:
                count = int((last.close - price) / brick_size_down)
                if count > 0:
                    new_bricks = create("down", count)

        logger.debug(f"Построено кирпичей: {len(new_bricks)}")
        return new_bricks

    def create_bricks(
        self,
        dt: datetime,
        direction: str,
        count: int,
        brick_size: Decimal,
        wick: Optional[Decimal] = None,
    ) -> List[RenkoBrick]:
        """
        Создаёт кирпичи.

        Args:
            dt (datetime): Время.
            direction (str): Направление ('up' или 'down').
            count (int): Количество.
            brick_size (Decimal): Размер кирпича.
            wick (Optional[Decimal]): Тень.

        Returns:
            List[RenkoBrick]: Список кирпичей.
        """
        new_bricks = []
        for _ in range(count):
            last_close = self.last_brick.close if self.bricks else 0
            new_open = last_close
            new_close = (
                last_close + brick_size
                if direction == "up"
                else last_close - brick_size
            )

            brick = RenkoBrick(
                timestamp=dt,
                type=direction,
                open=new_open,
                close=new_close,
                low=wick,
                high=wick,
            )
            new_bricks.append(brick)
        return new_bricks

    def position_should_be_closed(
        self,
        signal: TraderSignal,
        position: "TraderPosition",
    ) -> bool:
        """
        Проверяет, закрывать ли позицию.

        Args:
            signal (TraderSignal): Сигнал.
            position (TraderPosition): Позиция.

        Returns:
            bool: True, если закрывать.
        """
        return False


class MoneyFlowIndexStrategy(AbstractStrategy):
    """
    Стратегия на основе индикатора Money Flow Index (MFI).
    """

    PARAM_CONSTRAINTS = {
        "period": (10, 20),
        "overbought": (0, 100),
        "oversold": (0, 100),
        "median": (0, 100),
    }

    def __init__(
        self,
        period: int = 14,
        overbought: float = 70.0,
        oversold: float = 30.0,
        median: float = 50.0,
    ) -> None:
        """
        Инициализация MFI-стратегии.

        Args:
            period (int): Период MFI. По умолчанию 14.
            overbought (float): Уровень перекупленности. По умолчанию 70.0.
            oversold (float): Уровень перепроданности. По умолчанию 30.0.
            median (float): Медиана. По умолчанию 50.0.
        """
        self.period = period
        self.overbought = overbought
        self.oversold = oversold
        self.median = median

    def get_signal(self, trader: "Trader", candle: Candle) -> TraderSignal:
        """
        Генерирует сигнал на основе MFI.

        Args:
            trader (Trader): Экземпляр трейдера.
            candle (Candle): Текущая свеча.

        Returns:
            TraderSignal: Торговый сигнал.
        """
        logger.debug(f"Получена свеча: {candle}")

        candles = trader.candles + [candle]
        df = pd.DataFrame(
            [c.model_dump(exclude={"dt_unix"}) for c in candles],
            dtype="float64",
        )

        mfi = ta.mfi(
            high=df["high"],
            low=df["low"],
            close=df["close"],
            volume=df["volume"],
            length=self.period,
        )

        if mfi is None:
            logger.warning("Недостаточно данных для расчёта MFI")
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                price=candle.close,
                data={},
            )

        mfi_value = float(mfi.iloc[-1])
        data = MFIData(mfi_value=mfi_value).model_dump()

        signal_types = {
            mfi_value < self.oversold: SignalType.SELL,
            mfi_value > self.overbought: SignalType.BUY,
        }
        signal_type = signal_types.get(True, SignalType.WAIT)

        return TraderSignal(
            timestamp=candle.timestamp,
            type=signal_type,
            price=candle.close,
            data=data,
        )

    def position_should_be_closed(
        self,
        signal: TraderSignal,
        position: "TraderPosition",
    ) -> bool:
        """
        Проверяет закрытие позиции.

        Args:
            signal (TraderSignal): Сигнал.
            position (TraderPosition): Позиция.

        Returns:
            bool: True, если закрывать.
        """
        try:
            mfi_value = MFIData(**signal.data).mfi_value
        except Exception:
            return False

        if position.type == PositionType.LONG:
            return mfi_value < self.median
        elif position.type == PositionType.SHORT:
            return mfi_value > self.median
        return False


class CounterMoneyFlowIndexStrategy(AbstractStrategy):
    """
    Стратегия на основе индикатора Money Flow Index (MFI).
    """

    PARAM_CONSTRAINTS = {
        "period": (10, 20),
        "overbought": (0, 100),
        "oversold": (0, 100),
        "median": (0, 100),
    }

    def __init__(
        self,
        period: int = 14,
        overbought: float = 70.0,
        oversold: float = 30.0,
        median: float = 50.0,
    ) -> None:
        """
        Инициализация MFI-стратегии.

        Args:
            period (int): Период MFI. По умолчанию 14.
            overbought (float): Уровень перекупленности. По умолчанию 70.0.
            oversold (float): Уровень перепроданности. По умолчанию 30.0.
            median (float): Медиана. По умолчанию 50.0.
        """
        self.period = period
        self.overbought = overbought
        self.oversold = oversold
        self.median = median

    def get_signal(self, trader: "Trader", candle: Candle) -> TraderSignal:
        """
        Генерирует сигнал на основе MFI.

        Args:
            trader (Trader): Экземпляр трейдера.
            candle (Candle): Текущая свеча.

        Returns:
            TraderSignal: Торговый сигнал.
        """
        logger.debug(f"Получена свеча: {candle}")

        candles = trader.candles + [candle]
        df = pd.DataFrame(
            [c.model_dump(exclude={"dt_unix"}) for c in candles],
            dtype="float64",
        )

        mfi = ta.mfi(
            high=df["high"],
            low=df["low"],
            close=df["close"],
            volume=df["volume"],
            length=self.period,
        )

        if mfi is None:
            logger.warning("Недостаточно данных для расчёта MFI")
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                price=candle.close,
                data={},
            )

        mfi_value = float(mfi.iloc[-1])
        data = MFIData(mfi_value=mfi_value).model_dump()

        signal_types = {
            mfi_value < self.oversold: SignalType.BUY,
            mfi_value > self.overbought: SignalType.SELL,
        }
        signal_type = signal_types.get(True, SignalType.WAIT)

        return TraderSignal(
            timestamp=candle.timestamp,
            type=signal_type,
            price=candle.close,
            data=data,
        )

    def position_should_be_closed(
        self,
        signal: TraderSignal,
        position: "TraderPosition",
    ) -> bool:
        """
        Проверяет закрытие позиции.

        Args:
            signal (TraderSignal): Сигнал.
            position (TraderPosition): Позиция.

        Returns:
            bool: True, если закрывать.
        """
        try:
            mfi_value = MFIData(**signal.data).mfi_value
        except Exception:
            return False

        if position.type == PositionType.LONG:
            return mfi_value > self.median
        elif position.type == PositionType.SHORT:
            return mfi_value < self.median
        return False


class StochasticStrategy(AbstractStrategy):
    """
    Стратегия на основе стохастического осциллятора.
    """

    PARAM_CONSTRAINTS = {
        "k_period": (10, 20),
        "d_period": (1, 10),
        "overbought": (0, 100),
        "oversold": (0, 100),
        "median": (0, 100),
    }

    def __init__(
        self,
        k_period: int = 14,
        d_period: int = 3,
        overbought: float = 80,
        oversold: float = 20,
        median: float = 50,
    ) -> None:
        """
        Инициализация Stochastic-стратегии.

        Args:
            k_period (int): Период K. По умолчанию 14.
            d_period (int): Период D. По умолчанию 3.
            overbought (float): Перекупленность. По умолчанию 80.
            oversold (float): Перепроданность. По умолчанию 20.
            median (float): Медиана. По умолчанию 50.
        """
        if not isinstance(k_period, int) or k_period <= 0:
            raise ValueError("k_period must be a positive integer.")
        if not isinstance(d_period, int) or d_period <= 0:
            raise ValueError("d_period must be a positive integer.")
        if not (0 <= oversold <= 100):
            raise ValueError("oversold must be between 0 and 100.")
        if not (0 <= overbought <= 100):
            raise ValueError("overbought must be between 0 and 100.")
        if not (0 <= median <= 100):
            raise ValueError("median must be between 0 and 100.")

        self.k_period = k_period
        self.d_period = d_period
        self.overbought = overbought
        self.oversold = oversold
        self.median = median

    def get_signal(self, trader: "Trader", candle: Candle) -> TraderSignal:
        """
        Генерирует сигнал на основе K/D.

        Args:
            trader (Trader): Экземпляр трейдера.
            candle (Candle): Текущая свеча.

        Returns:
            TraderSignal: Торговый сигнал.
        """
        logger.debug(f"Получена свеча: {candle}")

        candles = trader.candles + [candle]
        last_candles = candles[-self.k_period :]

        if len(last_candles) < self.k_period:
            logger.warning("Недостаточно данных для расчёта стохастика")
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                price=candle.close,
                data={},
            )

        df = pd.DataFrame(
            [c.model_dump(exclude={"dt_unix"}) for c in last_candles],
            dtype="float64",
        )

        low_min, high_max = df["low"].min(), df["high"].max()
        k_value = self.median
        if high_max != low_min:
            k_value = 100 * (float(candle.close) - low_min) / (high_max - low_min)

        k_values = [
            StochasticData(**signal.data).k_value
            for signal in trader.signals
            if signal.data
        ] + [k_value]

        d_value = pd.Series(k_values).rolling(window=self.d_period).mean().iloc[-1]

        if pd.isna(d_value):
            logger.warning("Недостаточно данных для расчёта D")
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                price=candle.close,
                data=StochasticData(k_value=k_value, d_value=None).model_dump(),
            )

        data = StochasticData(k_value=k_value, d_value=d_value).model_dump()
        signal_types = {
            d_value < self.oversold: SignalType.SELL,
            d_value > self.overbought: SignalType.BUY,
        }
        signal_type = signal_types.get(True, SignalType.WAIT)

        return TraderSignal(
            timestamp=candle.timestamp,
            type=signal_type,
            price=candle.close,
            data=data,
        )

    def position_should_be_closed(
        self,
        signal: TraderSignal,
        position: "TraderPosition",
    ) -> bool:
        """
        Проверяет закрытие позиции.

        Args:
            signal (TraderSignal): Сигнал.
            position (TraderPosition): Позиция.

        Returns:
            bool: True, если закрывать.
        """
        try:
            d_value = StochasticData(**signal.data).d_value
        except Exception:
            return False

        if position.type == PositionType.LONG:
            return d_value < self.median
        elif position.type == PositionType.SHORT:
            return d_value > self.median
        return False


class CounterStochasticStrategy(AbstractStrategy):
    """
    Стратегия на основе стохастического осциллятора.

    Эта стратегия генерирует торговые сигналы на основе значений K и D стохастического осциллятора.
    Сигналы BUY генерируются при перепроданности (оба значения ниже oversold и K > D),
    SELL при перекупленности (оба значения выше overbought и K < D).
    """

    PARAM_CONSTRAINTS = {
        "k_period": (10, 20),
        "d_period": (1, 10),
        "overbought": (0, 100),
        "oversold": (0, 100),
        "median": (0, 100),
    }

    def __init__(
        self,
        k_period: int = 14,
        d_period: int = 3,
        overbought: float = 80,
        oversold: float = 20,
        median: float = 50,
    ) -> None:
        """
        Инициализация Stochastic-стратегии.

        Args:
            k_period (int): Период K. По умолчанию 14.
            d_period (int): Период D. По умолчанию 3.
            overbought (float): Перекупленность. По умолчанию 80.
            oversold (float): Перепроданность. По умолчанию 20.
            median (float): Медиана. По умолчанию 50.
        """
        if not isinstance(k_period, int) or k_period <= 0:
            raise ValueError("k_period must be a positive integer.")
        if not isinstance(d_period, int) or d_period <= 0:
            raise ValueError("d_period must be a positive integer.")
        if not (0 <= oversold <= 100):
            raise ValueError("oversold must be between 0 and 100.")
        if not (0 <= overbought <= 100):
            raise ValueError("overbought must be between 0 and 100.")
        if not (0 <= median <= 100):
            raise ValueError("median must be between 0 and 100.")

        self.k_period = k_period
        self.d_period = d_period
        self.overbought = overbought
        self.oversold = oversold
        self.median = median

    def get_signal(self, trader: "Trader", candle: Candle) -> TraderSignal:
        """
        Генерирует сигнал на основе K/D.

        Args:
            trader (Trader): Экземпляр трейдера.
            candle (Candle): Текущая свеча.

        Returns:
            TraderSignal: Торговый сигнал.
        """
        logger.debug(f"Получена свеча: {candle}")

        candles = trader.candles + [candle]
        last_candles = candles[-self.k_period :]

        if len(last_candles) < self.k_period:
            logger.warning("Недостаточно данных для расчёта стохастика")
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                price=candle.close,
                data={},
            )

        df = pd.DataFrame(
            [c.model_dump(exclude={"dt_unix"}) for c in last_candles],
            dtype="float64",
        )

        low_min, high_max = df["low"].min(), df["high"].max()
        k_value = self.median
        if high_max != low_min:
            k_value = 100 * (float(candle.close) - low_min) / (high_max - low_min)

        k_values = [
            StochasticData(**signal.data).k_value
            for signal in trader.signals
            if signal.data
        ] + [k_value]

        d_value = pd.Series(k_values).rolling(window=self.d_period).mean().iloc[-1]

        if pd.isna(d_value):
            logger.warning("Недостаточно данных для расчёта D")
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                price=candle.close,
                data=StochasticData(k_value=k_value, d_value=None).model_dump(),
            )

        data = StochasticData(k_value=k_value, d_value=d_value).model_dump()
        signal_types = {
            d_value < self.oversold: SignalType.BUY,
            d_value > self.overbought: SignalType.SELL,
        }
        signal_type = signal_types.get(True, SignalType.WAIT)

        return TraderSignal(
            timestamp=candle.timestamp,
            type=signal_type,
            price=candle.close,
            data=data,
        )

    def position_should_be_closed(
        self,
        signal: TraderSignal,
        position: "TraderPosition",
    ) -> bool:
        """
        Проверяет закрытие позиции.

        Args:
            signal (TraderSignal): Сигнал.
            position (TraderPosition): Позиция.

        Returns:
            bool: True, если закрывать.
        """
        try:
            d_value = StochasticData(**signal.data).d_value
        except Exception:
            return False

        if position.type == PositionType.LONG:
            return d_value > self.median
        elif position.type == PositionType.SHORT:
            return d_value < self.median
        return False


class DonchianCrossoverStrategy(AbstractStrategy):

    PARAM_CONSTRAINTS = {
        "fast_period": (5, 15),
        "slow_period": (10, 20),
    }

    def __init__(self, fast_period: int = 8, slow_period: int = 12):
        """
        Инициализация стратегии пересечения каналов Дончиана

        Args:
            fast_period: период для быстрого канала (20 свечей)
            slow_period: период для медленного канала (120 свечей)
        """
        if not isinstance(fast_period, int) or fast_period <= 0:
            raise ValueError("fast_period must be a positive integer.")
        if not isinstance(slow_period, int) or slow_period <= 0:
            raise ValueError("slow_period must be a positive integer.")
        if fast_period >= slow_period:
            raise ValueError("fast_period must be less than slow_period.")

        self.fast_period = fast_period
        self.slow_period = slow_period

    def get_signal(self, trader: "Trader", candle: Candle) -> TraderSignal:
        """
        Возвращает торговый сигнал на основе текущего состояния стратегии.

        Returns:
            SignalType: BUY / SELL / WAIT.
        """

        logger.debug(f"Получена свеча: {candle}")

        candles = trader.candles + [candle]
        fast_period_candles = candles[:-1][-self.fast_period :]
        slow_period_candles = candles[:-1][-self.slow_period :]

        if (
            len(fast_period_candles) < self.fast_period
            or len(slow_period_candles) < self.slow_period
        ):
            logger.warning("Недостаточно данных для расчёта стохастика")
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                price=candle.close,
                data={},
            )

        fast_upper = float(max([bar.high for bar in fast_period_candles]))
        fast_lower = float(min([bar.low for bar in fast_period_candles]))

        slow_upper = float(max([bar.high for bar in slow_period_candles]))
        slow_lower = float(min([bar.low for bar in slow_period_candles]))

        data = DonchianCrossoverData(
            fast_upper=fast_upper,
            fast_lower=fast_lower,
            slow_upper=slow_upper,
            slow_lower=slow_lower,
        ).model_dump()

        if candle.close > slow_upper:
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.BUY,
                price=candle.close,
                data=data,
            )
        elif candle.close < slow_lower:
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.SELL,
                price=candle.close,
                data=data,
            )
        else:
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                price=candle.close,
                data=data,
            )

    def position_should_be_closed(
        self,
        signal: TraderSignal,
        position: "TraderPosition",
    ) -> bool:
        """
        Определяет, должны ли позиции быть закрыты на основе сигнала.

        """
        try:
            fast_lower = DonchianCrossoverData(**signal.data).fast_lower
            fast_upper = DonchianCrossoverData(**signal.data).fast_upper
        except Exception:
            return False

        if fast_lower and signal.price < fast_lower:
            return True

        elif fast_upper and signal.price > fast_upper:
            return True

        return False


class MovingAverageCrossoverStrategy(AbstractStrategy):
    """Коротко: стратегия пересечения скользящих. BUY — fast > slow (пересечение вверх),
    SELL — fast < slow (пересечение вниз), иначе WAIT."""

    PARAM_CONSTRAINTS = {
        "fast_period": (10, 80),
        "slow_period": (50, 250),
    }
    def __init__(self, fast_period: int = 50, slow_period: int = 200):
        """
        Инициализация стратегии пересечения скользящих

        Args:
            fast_period: период для быстрого канала (20 свечей)
            slow_period: период для медленного канала (120 свечей)
        """
        if not isinstance(fast_period, int) or fast_period <= 0:
            raise ValueError("fast_period must be a positive integer.")
        if not isinstance(slow_period, int) or slow_period <= 0:
            raise ValueError("slow_period must be a positive integer.")
        if fast_period >= slow_period:
            raise ValueError("fast_period must be less than slow_period.")
            
        self.fast_period = fast_period
        self.slow_period = slow_period

    def get_signal(self, trader: "Trader", candle: Candle) -> TraderSignal:
        """
        Возвращает торговый сигнал на основе текущего состояния стратегии.

        Returns:
            SignalType: BUY / SELL / WAIT.
        """

        logger.debug(f"Получена свеча: {candle}")

        candles = trader.candles + [candle]
        fast_period_candles = candles[-self.fast_period:]
        slow_period_candles = candles[-self.slow_period:]

        if len(fast_period_candles) < self.fast_period or len(slow_period_candles) < self.slow_period:
            logger.warning("Недостаточно данных для расчёта пересечения скользящих(MovingAverageCrossoverStrategy)")
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                price=candle.close,
                data={},
            )

        # используем pandas для расчёта средних
        fast_avg = float(pd.Series([float(c.close) for c in fast_period_candles]).mean())
        slow_avg = float(pd.Series([float(c.close) for c in slow_period_candles]).mean())


        data = MovingAverageCrossoverData(
            fast_avg=fast_avg,
            slow_avg=slow_avg
        ).model_dump()

        privous_signal = trader.signals[-1] 
        try:
            privous_data = MovingAverageCrossoverData(**privous_signal.data)
            privous_fast_avg = privous_data.fast_avg
            privous_slow_avg = privous_data.slow_avg   
        except Exception:   
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                price=candle.close,
                data=data,
            )


        # сигнал по пересечению скользящих
        if fast_avg > slow_avg and privous_fast_avg <= privous_slow_avg:
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.BUY,
                price=candle.close,
                data=data,
            )
        elif fast_avg < slow_avg and privous_fast_avg >= privous_slow_avg:
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.SELL,
                price=candle.close,
                data=data,
            )
        else:
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                price=candle.close,
                data=data,
            )


    def position_should_be_closed(
        self,
        signal: TraderSignal,
        position: "TraderPosition",
    ) -> bool:
        """
        Определяет, должны ли позиции быть закрыты на основе сигнала.

        """
        try:
            data = MovingAverageCrossoverData(**signal.data)
            fast_avg = data.fast_avg
            slow_avg = data.slow_avg
        except Exception:
            return False

        if position.type == PositionType.LONG:
            return fast_avg < slow_avg
        if position.type == PositionType.SHORT:
            return fast_avg > slow_avg
        return False

class GridTradingStrategy(AbstractStrategy):
    """
    Коротко: 
    Стратегия торговли, которая включает размещение ордеров на покупку и продажу на заданных интервалах выше и ниже текущей рыночной цены.
    SELL — Когда пересекаем вверхнюю линию.
    LONG — Когда пересекаем нижнюю линию.
    """
    PARAM_CONSTRAINTS = {
        "narrow_grid": (0.5, 4),
        "wide_grid": (0.5, 6),
        "period": (50, 300),
    }

    def __init__(self, narrow_grid: int = 2, wide_grid: int = 4, period: int = 240):
        """
        Инициализация стратегии 
        Args:
            narrow_grid: отклоенение от ATR для узного канала
            wide_grid: отклоенение от ATR для широкого канала
            period: период  канала (240 свечей)
        """
        
        if not isinstance(narrow_grid, int) or narrow_grid <= 0:
            raise ValueError("fast_period must be a positive integer.")
        if not isinstance(wide_grid, int) or wide_grid <= 0:
            raise ValueError("slow_period must be a positive integer.")
        if not isinstance(period, int) or period <= 0:
            raise ValueError("slow_period must be a positive integer.")
        if narrow_grid >= wide_grid:
            raise ValueError("fast_period must be less than slow_period.")
        
        self.narrow_grid = narrow_grid
        self.wide_grid = wide_grid
        self.period = period


    def get_signal(self, trader: "Trader", candle: Candle) -> TraderSignal:
        """
        Возвращает торговый сигнал на основе текущего состояния стратегии.

        Returns:
            SignalType: BUY / SELL / WAIT.
        """

        logger.debug(f"Получена свеча: {candle}")

        candles = trader.candles + [candle]
        period_candles = candles[-self.period:]

        if len(period_candles) < self.period:
            logger.warning("Недостаточно данных для расчёта пересечения скользящих(GridTradingStrategy)")
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                price=candle.close,
                data={},
            )

        # используем pandas для расчёта средних
        avg = float(pd.Series([float(c.close) for c in period_candles]).mean())
        candle_close = candle.close
        narrow_grid_up = avg * ((100+self.narrow_grid)/100)
        narrow_grid_down = avg * ((100-self.narrow_grid)/100)
        wide_grid_up = avg * ((100+self.wide_grid)/100)
        wide_grid_down = avg * ((100-self.wide_grid)/100)

        data = GridTradingData(
            avg=avg,
            candle_close=candle_close,
            narrow_grid_up = narrow_grid_up,
            narrow_grid_down = narrow_grid_down,
            wide_grid_up = wide_grid_up,
            wide_grid_down = wide_grid_down,
        ).model_dump()

        privous_signal = trader.signals[-1] 

        try:
            privous_data = GridTradingData(**privous_signal.data)
            privous_avg = privous_data.avg
            privous_candle_close = privous_data.candle_close
            privous_narrow_grid_up = privous_data.narrow_grid_up
            privous_narrow_grid_down = privous_data.narrow_grid_down
            privous_wide_grid_up = privous_data.wide_grid_up
            privous_wide_grid_down = privous_data.wide_grid_down

        except Exception as e:  
            logger.warning("Произошла ошибка: {e}")
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                price=candle.close,
                data=data,
            )

        # сигнал по пересечению скользящих
        if wide_grid_down > candle_close and privous_candle_close >= wide_grid_down:
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.BUY,
                price=candle.close,
                data=data,
            )
        elif wide_grid_up < candle_close and privous_candle_close <= privous_wide_grid_up:
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.SELL,
                price=candle.close,
                data=data,
            )
        else:
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                price=candle.close,
                data=data,
            )


    def position_should_be_closed(
        self,
        signal: TraderSignal,
        position: "TraderPosition",
    ) -> bool:
        """
        Определяет, должны ли позиции быть закрыты на основе сигнала.

        """
        try:
            data = GridTradingData(**signal.data)
            narrow_grid_up = data.narrow_grid_up
            narrow_grid_down = data.narrow_grid_down
            candle_close = data.candle_close
        except Exception:
            return False

        if position.type == PositionType.LONG:
            return narrow_grid_down < candle_close
        if position.type == PositionType.SHORT:
            return narrow_grid_up > candle_close
        return False

