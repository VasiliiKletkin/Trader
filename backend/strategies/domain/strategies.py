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
    MoneyFlowIndexStrategyData,
    RenkoBrick,
    RenkoData,
    SignalType,
    StochasticData,
    TraderSignal,
    DonchianCrossoverData,
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
        self.bricks = []  # Добавлено: инициализация списка кирпичей

        logger.info(
            f"RenkoStrategy инициализирована: threshold_up={threshold_up}, threshold_down={threshold_down}"
        )

    @property
    def last_brick(self) -> Optional[RenkoBrick]:
        return self.bricks[-1] if self.bricks else None

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
                candle=candle,
                type=SignalType.WAIT,
                data=RenkoData(bricks=new_bricks).model_dump(),
            )

        last_bricks: List[RenkoBrick] = bricks[-self.count_bricks :]

        if all(brick.type == "up" for brick in last_bricks):
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.BUY,
                candle=candle,
                data=RenkoData(bricks=new_bricks).model_dump(),
            )
        elif all(brick.type == "down" for brick in last_bricks):
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.SELL,
                candle=candle,
                data=RenkoData(bricks=new_bricks).model_dump(),
            )
        else:
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                candle=candle,
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

        last = self.last_brick  # Исправлено: используем property вместо None

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

        candles = trader.get_last_candles(self.period) + [candle]

        df = pd.DataFrame(
            [c.model_dump(exclude={"dt_unix", "ids"}) for c in candles],
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
                candle=candle,
                data={},
            )

        mfi_value = float(mfi.iloc[-1])
        data = MoneyFlowIndexStrategyData(mfi_value=mfi_value).model_dump()

        signal_types = {
            mfi_value < self.oversold: SignalType.SELL,
            mfi_value > self.overbought: SignalType.BUY,
        }
        signal_type = signal_types.get(True, SignalType.WAIT)

        return TraderSignal(
            timestamp=candle.timestamp,
            type=signal_type,
            candle=candle,
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
            mfi_value = MoneyFlowIndexStrategyData(**signal.data).mfi_value
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

        candles = trader.get_last_candles(self.period) + [candle]

        df = pd.DataFrame(
            [c.model_dump(exclude={"dt_unix", "ids"}) for c in candles],
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
                candle=candle,
                data={},
            )

        mfi_value = float(mfi.iloc[-1])
        data = MoneyFlowIndexStrategyData(mfi_value=mfi_value).model_dump()

        signal_types = {
            mfi_value < self.oversold: SignalType.BUY,
            mfi_value > self.overbought: SignalType.SELL,
        }
        signal_type = signal_types.get(True, SignalType.WAIT)

        return TraderSignal(
            timestamp=candle.timestamp,
            type=signal_type,
            candle=candle,
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
            mfi_value = MoneyFlowIndexStrategyData(**signal.data).mfi_value
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

        candles = trader.get_last_candles(self.k_period - 1) + [candle]

        if len(candles) < self.k_period:
            logger.warning("Недостаточно данных для расчёта стохастика")
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                candle=candle,
                data={},
            )

        df = pd.DataFrame(
            [c.model_dump(exclude={"dt_unix", "ids"}) for c in candles],
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
                candle=candle,
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
            candle=candle,
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

        candles = trader.get_last_candles(self.k_period - 1) + [candle]

        if len(candles) < self.k_period:
            logger.warning("Недостаточно данных для расчёта стохастика")
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                candle=candle,
                data={},
            )

        df = pd.DataFrame(
            [c.model_dump(exclude={"dt_unix", "ids"}) for c in candles],
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
                candle=candle,
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
            candle=candle,
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
        self.fast_period = fast_period
        self.slow_period = slow_period

    def get_signal(self, trader: "Trader", candle: Candle) -> TraderSignal:
        """
        Возвращает торговый сигнал на основе текущего состояния стратегии.

        Returns:
            SignalType: BUY / SELL / WAIT.
        """

        logger.debug(f"Получена свеча: {candle}")

        fast_period_candles = trader.get_last_candles(self.fast_period - 1) + [candle]
        slow_period_candles = trader.get_last_candles(self.slow_period - 1) + [candle]

        if (
            len(fast_period_candles) < self.fast_period
            or len(slow_period_candles) < self.slow_period
        ):
            logger.warning("Недостаточно данных для расчёта стохастика")
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                candle=candle,
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
                candle=candle,
                data=data,
            )
        elif candle.close < slow_lower:
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.SELL,
                candle=candle,
                data=data,
            )
        else:
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                candle=candle,
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

        if fast_lower and signal.candle.close < fast_lower:
            return True

        elif fast_upper and signal.candle.close > fast_upper:
            return True

        return False
