from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pandas as pd
import pandas_ta as ta
from loguru import logger

from exchanges.domain import Candle

from ..schemas import (
    DonchianCrossoverData,
    GridTradingData,
    MeanReversionChannelData,
    MoneyFlowIndexStrategyData,
    MovingAverageCrossoverData,
    PositionType,
    RenkoBrick,
    RenkoData,
    SignalType,
    StochasticData,
    TraderSignal,
)
from .base import AbstractStrategy

if TYPE_CHECKING:
    from ..schemas import TraderPosition
    from ..traders.traders import Trader


class RenkoStrategy(AbstractStrategy):
    """
    Реализация торговой стратегии на основе Renko-графиков.
    """

    THRESHOLD_UP_MIN = 0.1
    THRESHOLD_UP_MAX = 10.0
    THRESHOLD_UP_DEFAULT = 1.0

    THRESHOLD_DOWN_MIN = 0.1
    THRESHOLD_DOWN_MAX = 10.0
    THRESHOLD_DOWN_DEFAULT = 1.0

    COUNT_BRICKS_MIN = 1
    COUNT_BRICKS_MAX = 10
    COUNT_BRICKS_DEFAULT = 3

    PARAM_CONSTRAINTS = {
        "threshold_up": (THRESHOLD_UP_MIN, THRESHOLD_UP_MAX),
        "threshold_down": (THRESHOLD_DOWN_MIN, THRESHOLD_DOWN_MAX),
        "count_bricks": (COUNT_BRICKS_MIN, COUNT_BRICKS_MAX),
    }

    def __init__(
        self,
        threshold_up: float = THRESHOLD_UP_DEFAULT,
        threshold_down: float = THRESHOLD_DOWN_DEFAULT,
        count_bricks: int = COUNT_BRICKS_DEFAULT,
    ) -> None:
        """
        Инициализация RenkoStrategy.

        Args:
            threshold_up (float): Процент для кирпича вверх.
            threshold_down (float): Процент для кирпича вниз.
            count_bricks (int): Количество кирпичей для сигнала.
        """
        if not (self.THRESHOLD_UP_MIN <= threshold_up <= self.THRESHOLD_UP_MAX):
            raise ValueError(
                f"threshold_up должен быть в диапазоне "
                f"[{self.THRESHOLD_UP_MIN}, {self.THRESHOLD_UP_MAX}]."
            )
        if not (self.THRESHOLD_DOWN_MIN <= threshold_down <= self.THRESHOLD_DOWN_MAX):
            raise ValueError(
                f"threshold_down должен быть в диапазоне "
                f"[{self.THRESHOLD_DOWN_MIN}, {self.THRESHOLD_DOWN_MAX}]."
            )
        if not isinstance(count_bricks, int):
            raise TypeError("count_bricks должен быть целым числом.")
        if not (self.COUNT_BRICKS_MIN <= count_bricks <= self.COUNT_BRICKS_MAX):
            raise ValueError(
                f"count_bricks должен быть в диапазоне "
                f"[{self.COUNT_BRICKS_MIN}, {self.COUNT_BRICKS_MAX}]."
            )

        self.threshold_up = threshold_up
        self.threshold_down = threshold_down
        self.count_bricks = count_bricks
        self._low_wick: Decimal | None = None
        self._high_wick: Decimal | None = None
        self.bricks: list[RenkoBrick] = []  # Добавлено: инициализация списка кирпичей

        logger.info(
            f"RenkoStrategy инициализирована: threshold_up={threshold_up}, threshold_down={threshold_down}"
        )

    @property
    def last_brick(self) -> RenkoBrick | None:
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
                price=candle.close,
                candle=candle,
                type=SignalType.WAIT,
                data=RenkoData(bricks=new_bricks).model_dump(),
            )

        last_bricks: list[RenkoBrick | dict[str, Any]] = bricks[-self.count_bricks :]

        if all(
            (brick.type if isinstance(brick, RenkoBrick) else brick.get("type")) == "up"
            for brick in last_bricks
        ):
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.BUY,
                price=candle.close,
                candle=candle,
                data=RenkoData(bricks=new_bricks).model_dump(),
            )
        elif all(
            (brick.type if isinstance(brick, RenkoBrick) else brick.get("type"))
            == "down"
            for brick in last_bricks
        ):
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.SELL,
                price=candle.close,
                candle=candle,
                data=RenkoData(bricks=new_bricks).model_dump(),
            )
        else:
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                price=candle.close,
                candle=candle,
                data=RenkoData(bricks=new_bricks).model_dump(),
            )

    def _update_wick_min(self, wick: Decimal | None, price: Decimal) -> Decimal:
        return price if wick is None else min(wick, price)

    def _update_wick_max(self, wick: Decimal | None, price: Decimal) -> Decimal:
        return price if wick is None else max(wick, price)

    def build_bricks(self, candle: Candle, trader: "Trader") -> list[RenkoBrick]:
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
            direction: str, count: int, wick: Decimal | None = None
        ) -> list[RenkoBrick]:
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
        wick: Decimal | None = None,
    ) -> list[RenkoBrick]:
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

    PERIOD_MIN = 10
    PERIOD_MAX = 20
    PERIOD_DEFAULT = 14

    OVERBOUGHT_MIN = 0
    OVERBOUGHT_MAX = 100
    OVERBOUGHT_DEFAULT = 70.0

    OVERSOLD_MIN = 0
    OVERSOLD_MAX = 100
    OVERSOLD_DEFAULT = 30.0

    MEDIAN_MIN = 0
    MEDIAN_MAX = 100
    MEDIAN_DEFAULT = 50.0

    PARAM_CONSTRAINTS = {
        "period": (PERIOD_MIN, PERIOD_MAX),
        "overbought": (OVERBOUGHT_MIN, OVERBOUGHT_MAX),
        "oversold": (OVERSOLD_MIN, OVERSOLD_MAX),
        "median": (MEDIAN_MIN, MEDIAN_MAX),
    }

    def __init__(
        self,
        period: int = PERIOD_DEFAULT,
        overbought: float = OVERBOUGHT_DEFAULT,
        oversold: float = OVERSOLD_DEFAULT,
        median: float = MEDIAN_DEFAULT,
    ) -> None:
        """
        Инициализация MFI-стратегии.

        Args:
            period (int): Период MFI.
            overbought (float): Уровень перекупленности.
            oversold (float): Уровень перепроданности.
            median (float): Медиана.
        """
        if not isinstance(period, int):
            raise TypeError("period должен быть целым числом.")
        if not (self.PERIOD_MIN <= period <= self.PERIOD_MAX):
            raise ValueError(
                f"period должен быть в диапазоне [{self.PERIOD_MIN}, {self.PERIOD_MAX}]."
            )
        if not (self.OVERBOUGHT_MIN <= overbought <= self.OVERBOUGHT_MAX):
            raise ValueError(
                f"overbought должен быть в диапазоне [{self.OVERBOUGHT_MIN}, {self.OVERBOUGHT_MAX}]."
            )
        if not (self.OVERSOLD_MIN <= oversold <= self.OVERSOLD_MAX):
            raise ValueError(
                f"oversold должен быть в диапазоне [{self.OVERSOLD_MIN}, {self.OVERSOLD_MAX}]."
            )
        if not (self.MEDIAN_MIN <= median <= self.MEDIAN_MAX):
            raise ValueError(
                f"median должен быть в диапазоне [{self.MEDIAN_MIN}, {self.MEDIAN_MAX}]."
            )

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

        candles = [*trader.get_last_candles(self.period), candle]

        df = pd.DataFrame(
            [
                c.model_dump(include={"open", "high", "low", "close", "volume"})
                for c in candles
            ],
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
            price=candle.close,
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

    PERIOD_MIN = 10
    PERIOD_MAX = 20
    PERIOD_DEFAULT = 14

    OVERBOUGHT_MIN = 0
    OVERBOUGHT_MAX = 100
    OVERBOUGHT_DEFAULT = 70.0

    OVERSOLD_MIN = 0
    OVERSOLD_MAX = 100
    OVERSOLD_DEFAULT = 30.0

    MEDIAN_MIN = 0
    MEDIAN_MAX = 100
    MEDIAN_DEFAULT = 50.0

    PARAM_CONSTRAINTS = {
        "period": (PERIOD_MIN, PERIOD_MAX),
        "overbought": (OVERBOUGHT_MIN, OVERBOUGHT_MAX),
        "oversold": (OVERSOLD_MIN, OVERSOLD_MAX),
        "median": (MEDIAN_MIN, MEDIAN_MAX),
    }

    def __init__(
        self,
        period: int = PERIOD_DEFAULT,
        overbought: float = OVERBOUGHT_DEFAULT,
        oversold: float = OVERSOLD_DEFAULT,
        median: float = MEDIAN_DEFAULT,
    ) -> None:
        """
        Инициализация MFI-стратегии.

        Args:
            period (int): Период MFI.
            overbought (float): Уровень перекупленности.
            oversold (float): Уровень перепроданности.
            median (float): Медиана.
        """
        if not isinstance(period, int):
            raise TypeError("period должен быть целым числом.")
        if not (self.PERIOD_MIN <= period <= self.PERIOD_MAX):
            raise ValueError(
                f"period должен быть в диапазоне [{self.PERIOD_MIN}, {self.PERIOD_MAX}]."
            )
        if not (self.OVERBOUGHT_MIN <= overbought <= self.OVERBOUGHT_MAX):
            raise ValueError(
                f"overbought должен быть в диапазоне [{self.OVERBOUGHT_MIN}, {self.OVERBOUGHT_MAX}]."
            )
        if not (self.OVERSOLD_MIN <= oversold <= self.OVERSOLD_MAX):
            raise ValueError(
                f"oversold должен быть в диапазоне [{self.OVERSOLD_MIN}, {self.OVERSOLD_MAX}]."
            )
        if not (self.MEDIAN_MIN <= median <= self.MEDIAN_MAX):
            raise ValueError(
                f"median должен быть в диапазоне [{self.MEDIAN_MIN}, {self.MEDIAN_MAX}]."
            )

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

        candles = [*trader.get_last_candles(self.period), candle]

        df = pd.DataFrame(
            [
                c.model_dump(include={"open", "high", "low", "close", "volume"})
                for c in candles
            ],
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
            price=candle.close,
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

    K_PERIOD_MIN = 10
    K_PERIOD_MAX = 20
    K_PERIOD_DEFAULT = 14

    D_PERIOD_MIN = 1
    D_PERIOD_MAX = 10
    D_PERIOD_DEFAULT = 3

    OVERBOUGHT_MIN = 0
    OVERBOUGHT_MAX = 100
    OVERBOUGHT_DEFAULT = 80.0

    OVERSOLD_MIN = 0
    OVERSOLD_MAX = 100
    OVERSOLD_DEFAULT = 20.0

    MEDIAN_MIN = 0
    MEDIAN_MAX = 100
    MEDIAN_DEFAULT = 50.0

    PARAM_CONSTRAINTS = {
        "k_period": (K_PERIOD_MIN, K_PERIOD_MAX),
        "d_period": (D_PERIOD_MIN, D_PERIOD_MAX),
        "overbought": (OVERBOUGHT_MIN, OVERBOUGHT_MAX),
        "oversold": (OVERSOLD_MIN, OVERSOLD_MAX),
        "median": (MEDIAN_MIN, MEDIAN_MAX),
    }

    def __init__(
        self,
        k_period: int = K_PERIOD_DEFAULT,
        d_period: int = D_PERIOD_DEFAULT,
        overbought: float = OVERBOUGHT_DEFAULT,
        oversold: float = OVERSOLD_DEFAULT,
        median: float = MEDIAN_DEFAULT,
    ) -> None:
        """
        Инициализация Stochastic-стратегии.

        Args:
            k_period (int): Период K.
            d_period (int): Период D.
            overbought (float): Перекупленность.
            oversold (float): Перепроданность.
            median (float): Медиана.
        """
        if not isinstance(k_period, int):
            raise TypeError("k_period должен быть целым числом.")
        if not (self.K_PERIOD_MIN <= k_period <= self.K_PERIOD_MAX):
            raise ValueError(
                f"k_period должен быть в диапазоне [{self.K_PERIOD_MIN}, {self.K_PERIOD_MAX}]."
            )
        if not isinstance(d_period, int):
            raise TypeError("d_period должен быть целым числом.")
        if not (self.D_PERIOD_MIN <= d_period <= self.D_PERIOD_MAX):
            raise ValueError(
                f"d_period должен быть в диапазоне [{self.D_PERIOD_MIN}, {self.D_PERIOD_MAX}]."
            )
        if not (self.OVERBOUGHT_MIN <= overbought <= self.OVERBOUGHT_MAX):
            raise ValueError(
                f"overbought должен быть в диапазоне [{self.OVERBOUGHT_MIN}, {self.OVERBOUGHT_MAX}]."
            )
        if not (self.OVERSOLD_MIN <= oversold <= self.OVERSOLD_MAX):
            raise ValueError(
                f"oversold должен быть в диапазоне [{self.OVERSOLD_MIN}, {self.OVERSOLD_MAX}]."
            )
        if not (self.MEDIAN_MIN <= median <= self.MEDIAN_MAX):
            raise ValueError(
                f"median должен быть в диапазоне [{self.MEDIAN_MIN}, {self.MEDIAN_MAX}]."
            )

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

        candles = [*trader.get_last_candles(self.k_period - 1), candle]

        if len(candles) < self.k_period:
            logger.warning("Недостаточно данных для расчёта стохастика")
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                price=candle.close,
                candle=candle,
                data={},
            )

        df = pd.DataFrame(
            [
                c.model_dump(include={"open", "high", "low", "close", "volume"})
                for c in candles
            ],
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
            price=candle.close,
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

        if not d_value:
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

    K_PERIOD_MIN = 10
    K_PERIOD_MAX = 20
    K_PERIOD_DEFAULT = 14

    D_PERIOD_MIN = 1
    D_PERIOD_MAX = 10
    D_PERIOD_DEFAULT = 3

    OVERBOUGHT_MIN = 0
    OVERBOUGHT_MAX = 100
    OVERBOUGHT_DEFAULT = 80.0

    OVERSOLD_MIN = 0
    OVERSOLD_MAX = 100
    OVERSOLD_DEFAULT = 20.0

    MEDIAN_MIN = 0
    MEDIAN_MAX = 100
    MEDIAN_DEFAULT = 50.0

    PARAM_CONSTRAINTS = {
        "k_period": (K_PERIOD_MIN, K_PERIOD_MAX),
        "d_period": (D_PERIOD_MIN, D_PERIOD_MAX),
        "overbought": (OVERBOUGHT_MIN, OVERBOUGHT_MAX),
        "oversold": (OVERSOLD_MIN, OVERSOLD_MAX),
        "median": (MEDIAN_MIN, MEDIAN_MAX),
    }

    def __init__(
        self,
        k_period: int = K_PERIOD_DEFAULT,
        d_period: int = D_PERIOD_DEFAULT,
        overbought: float = OVERBOUGHT_DEFAULT,
        oversold: float = OVERSOLD_DEFAULT,
        median: float = MEDIAN_DEFAULT,
    ) -> None:
        """
        Инициализация Stochastic-стратегии.

        Args:
            k_period (int): Период K.
            d_period (int): Период D.
            overbought (float): Перекупленность.
            oversold (float): Перепроданность.
            median (float): Медиана.
        """
        if not isinstance(k_period, int):
            raise TypeError("k_period должен быть целым числом.")
        if not (self.K_PERIOD_MIN <= k_period <= self.K_PERIOD_MAX):
            raise ValueError(
                f"k_period должен быть в диапазоне [{self.K_PERIOD_MIN}, {self.K_PERIOD_MAX}]."
            )
        if not isinstance(d_period, int):
            raise TypeError("d_period должен быть целым числом.")
        if not (self.D_PERIOD_MIN <= d_period <= self.D_PERIOD_MAX):
            raise ValueError(
                f"d_period должен быть в диапазоне [{self.D_PERIOD_MIN}, {self.D_PERIOD_MAX}]."
            )
        if not (self.OVERBOUGHT_MIN <= overbought <= self.OVERBOUGHT_MAX):
            raise ValueError(
                f"overbought должен быть в диапазоне [{self.OVERBOUGHT_MIN}, {self.OVERBOUGHT_MAX}]."
            )
        if not (self.OVERSOLD_MIN <= oversold <= self.OVERSOLD_MAX):
            raise ValueError(
                f"oversold должен быть в диапазоне [{self.OVERSOLD_MIN}, {self.OVERSOLD_MAX}]."
            )
        if not (self.MEDIAN_MIN <= median <= self.MEDIAN_MAX):
            raise ValueError(
                f"median должен быть в диапазоне [{self.MEDIAN_MIN}, {self.MEDIAN_MAX}]."
            )

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

        candles = [*trader.get_last_candles(self.k_period - 1), candle]

        if len(candles) < self.k_period:
            logger.warning("Недостаточно данных для расчёта стохастика")
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                price=candle.close,
                candle=candle,
                data={},
            )

        df = pd.DataFrame(
            [
                c.model_dump(include={"open", "high", "low", "close", "volume"})
                for c in candles
            ],
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
                candle=candle,
                data=StochasticData(k_value=k_value, d_value=None).model_dump(),
            )

        data = StochasticData(k_value=k_value, d_value=d_value).model_dump()

        privous_signal = trader.signals[-1]

        try:
            privous_data = StochasticData(**privous_signal.data)
            privous_d_value = privous_data.d_value
        except Exception:
            logger.warning("Произошла ошибка: {e}")
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                price=candle.close,
                candle=candle,
                data=data,
            )

        if privous_d_value is None:
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                price=candle.close,
                candle=candle,
                data=data,
            )

        signal_types = {
            privous_d_value < self.oversold
            and d_value >= self.oversold: SignalType.BUY,
            privous_d_value > self.overbought
            and d_value <= self.overbought: SignalType.SELL,
        }
        signal_type = signal_types.get(True, SignalType.WAIT)

        return TraderSignal(
            timestamp=candle.timestamp,
            type=signal_type,
            price=candle.close,
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

        if not d_value:
            return False
        if position.type == PositionType.LONG:
            return d_value > self.median
        elif position.type == PositionType.SHORT:
            return d_value < self.median
        return False


class DonchianCrossoverStrategy(AbstractStrategy):
    """
    Стратегия пересечения каналов Дончиана.
    """

    FAST_PERIOD_MIN = 5
    FAST_PERIOD_MAX = 15
    FAST_PERIOD_DEFAULT = 8

    SLOW_PERIOD_MIN = 10
    SLOW_PERIOD_MAX = 20
    SLOW_PERIOD_DEFAULT = 12

    PARAM_CONSTRAINTS = {
        "fast_period": (FAST_PERIOD_MIN, FAST_PERIOD_MAX),
        "slow_period": (SLOW_PERIOD_MIN, SLOW_PERIOD_MAX),
    }

    def __init__(
        self,
        fast_period: int = FAST_PERIOD_DEFAULT,
        slow_period: int = SLOW_PERIOD_DEFAULT,
    ):
        """
        Инициализация стратегии пересечения каналов Дончиана.

        Args:
            fast_period: Период для быстрого канала.
            slow_period: Период для медленного канала.
        """
        if not isinstance(fast_period, int):
            raise TypeError("fast_period должен быть целым числом.")
        if not (self.FAST_PERIOD_MIN <= fast_period <= self.FAST_PERIOD_MAX):
            raise ValueError(
                f"fast_period должен быть в диапазоне [{self.FAST_PERIOD_MIN}, {self.FAST_PERIOD_MAX}]."
            )
        if not isinstance(slow_period, int):
            raise TypeError("slow_period должен быть целым числом.")
        if not (self.SLOW_PERIOD_MIN <= slow_period <= self.SLOW_PERIOD_MAX):
            raise ValueError(
                f"slow_period должен быть в диапазоне [{self.SLOW_PERIOD_MIN}, {self.SLOW_PERIOD_MAX}]."
            )

        self.fast_period = fast_period
        self.slow_period = slow_period

    def get_signal(self, trader: "Trader", candle: Candle) -> TraderSignal:
        """
        Возвращает торговый сигнал на основе текущего состояния стратегии.

        Returns:
            SignalType: BUY / SELL / WAIT.
        """

        logger.debug(f"Получена свеча: {candle}")

        fast_period_candles = [*trader.get_last_candles(self.fast_period - 1), candle]
        slow_period_candles = [*trader.get_last_candles(self.slow_period - 1), candle]

        if (
            len(fast_period_candles) < self.fast_period
            or len(slow_period_candles) < self.slow_period
        ):
            logger.warning("Недостаточно данных для расчёта каналов Дончиана")
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                price=candle.close,
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
            candle_low=candle.low,
            candle_high=candle.high,
        ).model_dump()

        if candle.high > slow_upper:
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.BUY,
                price=candle.close,
                candle=candle,
                data=data,
            )
        elif candle.low < slow_lower:
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.SELL,
                price=candle.close,
                candle=candle,
                data=data,
            )
        else:
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                price=candle.close,
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
            data = DonchianCrossoverData(**signal.data)
            fast_lower = data.fast_lower
            fast_upper = data.fast_upper
        except Exception:
            return False

        if position.type == PositionType.LONG:
            return float(signal.price) < fast_lower

        if position.type == PositionType.SHORT:
            return float(signal.price) > fast_upper

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

        candles = [*trader.candles, candle]
        fast_period_candles = candles[-self.fast_period :]
        slow_period_candles = candles[-self.slow_period :]

        if (
            len(fast_period_candles) < self.fast_period
            or len(slow_period_candles) < self.slow_period
        ):
            logger.warning(
                "Недостаточно данных для расчёта пересечения скользящих(MovingAverageCrossoverStrategy)"
            )
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                price=candle.close,
                candle=candle,
                data={},
            )

        # используем pandas для расчёта средних
        fast_avg = float(
            pd.Series([float(c.close) for c in fast_period_candles]).mean()
        )
        slow_avg = float(
            pd.Series([float(c.close) for c in slow_period_candles]).mean()
        )

        data = MovingAverageCrossoverData(
            fast_avg=fast_avg, slow_avg=slow_avg
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
                candle=candle,
                data=data,
            )

        # сигнал по пересечению скользящих
        if fast_avg > slow_avg and privous_fast_avg <= privous_slow_avg:
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.BUY,
                price=candle.close,
                candle=candle,
                data=data,
            )
        elif fast_avg < slow_avg and privous_fast_avg >= privous_slow_avg:
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.SELL,
                price=candle.close,
                candle=candle,
                data=data,
            )
        else:
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                price=candle.close,
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

    def __init__(self, narrow_grid: int = 6, wide_grid: int = 12, period: int = 240):
        """
        Инициализация стратегии
        Args:
            narrow_grid: отклоенение от ATR для узного канала
            wide_grid: отклоенение от ATR для широкого канала
            period: период  канала (240 свечей)
        """

        if not isinstance(narrow_grid, int) or narrow_grid <= 0:
            raise ValueError("narrow_grid must be a positive integer.")
        if not isinstance(wide_grid, int) or wide_grid <= 0:
            raise ValueError("wide_grid must be a positive integer.")
        if not isinstance(period, int) or period <= 0:
            raise ValueError("period must be a positive integer.")
        if narrow_grid >= wide_grid:
            raise ValueError("narrow_grid must be less than wide_grid.")

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

        candles = [*trader.candles, candle]
        period_candles = candles[-self.period :]

        if len(period_candles) < self.period:
            logger.warning(
                "Недостаточно данных для расчёта пересечения скользящих(GridTradingStrategy)"
            )
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                price=candle.close,
                candle=candle,
                data={},
            )

        df_period = pd.DataFrame(
            [c.model_dump(exclude={"dt_unix"}) for c in period_candles]
        )
        df_period["close"] = pd.to_numeric(
            df_period.get("close", pd.Series()), errors="coerce"
        )
        df_period["high"] = pd.to_numeric(
            df_period.get("high", pd.Series()), errors="coerce"
        )
        df_period["low"] = pd.to_numeric(
            df_period.get("low", pd.Series()), errors="coerce"
        )

        if df_period["close"].dropna().empty:
            logger.warning(
                "Нет числовых значений close для расчёта avg (GridTradingStrategy)"
            )
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                price=candle.close,
                candle=candle,
                data={},
            )

        avg = float(df_period["close"].mean())

        try:
            candle_close = float(candle.close)
        except Exception:
            logger.warning(
                "Не удалось привести candle.close к числу, используем последнее значение close из периода"
            )
            candle_close = float(df_period["close"].dropna().iloc[-1])

        try:
            atr_series = ta.atr(
                high=df_period["high"],
                low=df_period["low"],
                close=df_period["close"],
                length=self.period,
            )
            atr_val = atr_series.iloc[-1] if atr_series is not None else None
            atr = float(atr_val) if pd.notna(atr_val) else None
        except Exception as e:
            logger.debug(f"ATR calculation failed: {e}")
            atr = None

        if atr is None:
            try:
                atr_fallback = (df_period["high"] - df_period["low"]).abs().mean()
                atr = float(atr_fallback) if pd.notna(atr_fallback) else 0.0
                logger.debug(f"Using ATR fallback: {atr}")
            except Exception:
                atr = 0.0

        narrow_grid_up = avg + atr * self.narrow_grid
        narrow_grid_down = avg - atr * self.narrow_grid
        wide_grid_up = avg + atr * self.wide_grid
        wide_grid_down = avg - atr * self.wide_grid

        data = GridTradingData(
            avg=avg,
            candle_close=candle_close,
            narrow_grid_up=narrow_grid_up,
            narrow_grid_down=narrow_grid_down,
            wide_grid_up=wide_grid_up,
            wide_grid_down=wide_grid_down,
        ).model_dump()

        data["atr"] = atr

        privous_signal = trader.signals[-1]

        try:
            privous_data = GridTradingData(**privous_signal.data)
            privous_candle_close = privous_data.candle_close
            privous_wide_grid_up = privous_data.wide_grid_up
            # privous_atr = privous_data.atr

        except Exception:
            logger.warning("Произошла ошибка: {e}")
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                price=candle.close,
                candle=candle,
                data=data,
            )

        # сигнал по пересечению скользящих
        if wide_grid_down > candle_close and privous_candle_close >= wide_grid_down:
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.BUY,
                price=candle.close,
                candle=candle,
                data=data,
            )
        elif (
            wide_grid_up < candle_close and privous_candle_close <= privous_wide_grid_up
        ):
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.SELL,
                price=candle.close,
                candle=candle,
                data=data,
            )
        else:
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.WAIT,
                price=candle.close,
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


class MeanReversionChannelStrategy(AbstractStrategy):
    """Mean reversion channel по `open`.

    Параметры:
    - period: окно для SMA/std (по умолчанию 150)
    - sigma_mult: множитель сигмы (по умолчанию 2.0)
    - threshold: относительный порог выхода за границу (дефолт 0.01 = 1%)

    Логика:
    - считаем SMA и std по `open` за последние `period` таймфреймов;
    - коридор = SMA +/- sigma_mult * std;
    - если close < (1 - threshold) * lower -> BUY;
      если close > (1 + threshold) * upper -> SELL;
    - при открытой позиции закрываем её, когда цена достигает SMA (signal.price сравнивается с SMA).
    """

    PARAM_CONSTRAINTS = {
        "period": (50, 500),
        "sigma_mult": (0.5, 4.0),
        "threshold": (0.001, 0.1),
    }

    def __init__(
        self, period: int = 150, sigma_mult: float = 2.0, threshold: float = 0.01
    ):
        self.period = int(period)
        self.sigma_mult = float(sigma_mult)
        self.threshold = float(threshold)

    def get_signal(self, trader: "Trader", candle: Candle) -> TraderSignal:
        candles = [*trader.candles, candle]
        opens = pd.Series([c.open for c in candles])
        opens = pd.to_numeric(opens, errors="coerce").dropna()

        if len(opens) < self.period:
            return TraderSignal(
                timestamp=candle.timestamp,
                candle=candle,
                type=SignalType.WAIT,
                price=candle.close,
                data={},
            )

        window = opens.iloc[-self.period :]
        sma = float(window.mean())
        std = float(window.std(ddof=0))
        upper = sma + self.sigma_mult * std
        lower = sma - self.sigma_mult * std

        try:
            close = float(candle.close)
        except Exception:
            return TraderSignal(
                timestamp=candle.timestamp,
                candle=candle,
                type=SignalType.WAIT,
                price=candle.close,
                data={},
            )

        data = MeanReversionChannelData(
            sma=sma,
            std=std,
            upper=upper,
            lower=lower,
            period=self.period,
            sigma_mult=self.sigma_mult,
            threshold=self.threshold,
        ).model_dump()

        # проверка выхода за границы с порогом
        if close < (1.0 - self.threshold) * lower:
            return TraderSignal(
                timestamp=candle.timestamp,
                candle=candle,
                type=SignalType.BUY,
                price=candle.close,
                data=data,
            )
        if close > (1.0 + self.threshold) * upper:
            return TraderSignal(
                timestamp=candle.timestamp,
                candle=candle,
                type=SignalType.SELL,
                price=candle.close,
                data=data,
            )
        return TraderSignal(
            timestamp=candle.timestamp,
            candle=candle,
            type=SignalType.WAIT,
            price=candle.close,
            data=data,
        )

    def position_should_be_closed(
        self, signal: TraderSignal, position: "TraderPosition"
    ) -> bool:
        try:
            data = MeanReversionChannelData(**signal.data)
            sma = data.sma
        except Exception:
            return False

        try:
            price = float(signal.price)
        except Exception:
            return False

        if position.type == PositionType.LONG:
            return price >= sma
        if position.type == PositionType.SHORT:
            return price <= sma
        return False
