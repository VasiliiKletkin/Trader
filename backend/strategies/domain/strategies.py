from datetime import datetime
from decimal import Decimal
from typing import List, Optional, TYPE_CHECKING, Tuple

import pandas as pd
import pandas_ta as ta
from risk_managers.domain.schemas import (
    PositionCloseReason,
    PositionType,
    TraderPosition,
)
from exchanges.domain.schemas import Candle
from loguru import logger

from .base import AbstractStrategy
from .schemas import RenkoBrick, MFIData, RenkoData
from core.domain.types import SignalType, TraderSignal

if TYPE_CHECKING:
    from traders.domain.traders import Trader


class RenkoStrategy(AbstractStrategy):
    """
    Реализация торговой стратегии на основе Renko-графиков.
    """

    def __init__(
        self,
        threshold_up: float = 1.0,
        threshold_down: float = 1.0,
        count_bricks: int = 3,
    ) -> None:
        """
        :param threshold_up: Процент изменения цены для формирования кирпича вверх
        :param threshold_down: Процент изменения цены для формирования кирпича вниз
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
        Возвращает торговый сигнал на основе последних кирпичей.
        - BUY: 3 подряд вверх
        - SELL: 3 подряд вниз
        - OTHERWISE: WAIT
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
        Строит новые кирпичи на основе поступившей свечи.

        Args:
            candle (Candle): Входящая свеча.

        Returns:
            List[RenkoBrick]: Список новых кирпичей (может быть пустым).
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
        Создаёт список кирпичей по направлению и количеству.

        Args:
            dt (datetime): Временная метка для кирпичей.
            direction (str): Направление ('up' или 'down').
            count (int): Количество кирпичей.
            brick_size (Decimal): Размер одного кирпича.
            wick (Optional[Decimal]): Верхняя или нижняя тень.

        Returns:
            List[RenkoBrick]: Список созданных кирпичей.
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

    def positions_should_be_closed(
        self,
        signal: TraderSignal,
        position: TraderPosition,
    ) -> Tuple[bool, PositionCloseReason | None]:
        return False, None


class MFIStrategy(AbstractStrategy):
    """
    Стратегия на основе индикатора Money Flow Index (MFI).
    """

    def __init__(
        self,
        period: int = 14,
        overbought: float = 70.0,
        oversold: float = 30.0,
        median: float = 50.0,
    ) -> None:
        """Инициализация стратегии.
        Args:
            period (int): Период MFI. По умолчанию 14.
            overbought (float): Уровень перекупленности. По умолчанию 70.0.
            oversold (float): Уровень перепроданности. По умолчанию 30.0.
        """
        self.period = period
        self.overbought = overbought
        self.oversold = oversold
        self.median = median

    def get_signal(self, trader: "Trader", candle: Candle) -> TraderSignal:
        """
        Генерирует торговые сигналы на основе последнего значения MFI.
        """
        logger.debug(f"Получена свеча: {candle}")

        candles = trader.candles + [candle]
        last_candles = candles[-self.period :]

        if len(last_candles) < self.period:
            logger.warning("Недостаточно данных для расчёта MFI: нет свечей")
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

        mfi = ta.mfi(
            high=df["high"],
            low=df["low"],
            close=df["close"],
            volume=df["volume"],
            length=self.period,
        )

        mfi_value = float(mfi.iloc[-1])

        mfi_data = MFIData(mfi_value=mfi_value).model_dump()

        if mfi_value < self.oversold:
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.SELL,
                price=candle.close,
                data=mfi_data,
            )
        elif mfi_value > self.overbought:
            return TraderSignal(
                timestamp=candle.timestamp,
                type=SignalType.BUY,
                price=candle.close,
                data=mfi_data,
            )
        return TraderSignal(
            timestamp=candle.timestamp,
            type=SignalType.WAIT,
            price=candle.close,
            data=mfi_data,
        )

    def positions_should_be_closed(
        self,
        signal: TraderSignal,
        position: TraderPosition,
    ) -> Tuple[bool, PositionCloseReason | None]:

        try:
            current_mfi_value = MFIData(**signal.data).mfi_value
        except Exception:
            return False, None

        if position.type == PositionType.LONG:
            return current_mfi_value < self.median, PositionCloseReason.STRATEGY
        elif position.type == PositionType.SHORT:
            return current_mfi_value > self.median, PositionCloseReason.STRATEGY
        return False, None
