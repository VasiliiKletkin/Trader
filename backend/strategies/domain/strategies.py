from collections import deque
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

import pandas as pd
import pandas_ta as ta
from exchanges.domain.schemas import Candle
from loguru import logger

from .base import AbstractStrategy
from .schemas import RenkoBrick, SignalType, MFIState


class RenkoStrategy(AbstractStrategy):
    """
    Реализация торговой стратегии на основе Renko-графиков.
    """

    def __init__(
        self,
        threshold_up: float = 1.0,
        threshold_down: float = 1.0,
    ) -> None:
        """
        :param threshold_up: Процент изменения цены для формирования кирпича вверх
        :param threshold_down: Процент изменения цены для формирования кирпича вниз
        """
        self.threshold_up = threshold_up
        self.threshold_down = threshold_down
        self.bricks: List[RenkoBrick] = []
        self._low_wick: Optional[Decimal] = None
        self._high_wick: Optional[Decimal] = None

        logger.info(
            f"RenkoStrategy инициализирована: threshold_up={threshold_up}, threshold_down={threshold_down}"
        )

    def get_signal(self, candle: Candle) -> SignalType:
        """
        Возвращает торговый сигнал на основе последних кирпичей.
        - BUY: 3 подряд вверх
        - SELL: 3 подряд вниз
        - OTHERWISE: WAIT
        """
        logger.debug(f"Обработка свечи: {candle}")
        new_bricks = self.build_bricks(candle)

        self.bricks.extend(new_bricks)

        if len(self.bricks) < 3:
            return SignalType.WAIT

        last_part: List[RenkoBrick] = self.bricks[-3:]

        if all(brick.type == "up" for brick in last_part):
            return SignalType.BUY
        elif all(brick.type == "down" for brick in last_part):
            return SignalType.SELL
        else:
            return SignalType.WAIT

    def load_state(self, data: Dict[str, Any]) -> None:
        """
        Загружает состояние стратегии (восстановление при перезапуске).
        """
        bricks = data.get("state", [])
        self.bricks = [RenkoBrick(**brick) for brick in bricks]

    def dump_state(self) -> Dict[str, Any]:
        """
        Сохраняет текущее состояние стратегии (для восстановления при перезапуске).
        """
        return {
            "state": [brick.model_dump(mode="json") for brick in self.bricks],
        }

    @property
    def last_brick(self) -> Optional[RenkoBrick]:
        return self.bricks[-1] if self.bricks else None

    def _update_wick_min(self, wick: Optional[Decimal], price: Decimal) -> Decimal:
        return price if wick is None else min(wick, price)

    def _update_wick_max(self, wick: Optional[Decimal], price: Decimal) -> Decimal:
        return price if wick is None else max(wick, price)

    def build_bricks(self, candle: Candle) -> List[RenkoBrick]:
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
        last = self.last_brick

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


class MFIStrategy(AbstractStrategy):
    """
    Стратегия на основе индикатора Money Flow Index (MFI).
    """

    def __init__(
        self,
        period: int = 14,
        overbought: float = 70.0,
        oversold: float = 30.0,
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

        self.states: deque[MFIState] = deque()
        self.candles: deque[Candle] = deque(maxlen=self.period)

    def get_signal(self, candle: Candle) -> SignalType:
        """
        Генерирует торговые сигналы на основе последнего значения MFI.
        """
        logger.debug(f"Получена свеча: {candle}")
        self.candles.append(candle)

        if not self.candles or len(self.candles) < self.period:
            logger.warning("Недостаточно данных для расчёта MFI: нет свечей")
            return SignalType.WAIT

        df = pd.DataFrame(
            [c.model_dump(exclude={"dt_unix"}) for c in self.candles],
            dtype="float64",
        )
        numeric_cols = ["high", "low", "close", "open", "volume"]

        for col in numeric_cols:
            df[col] = df[col].astype("float64")

        mfi = ta.mfi(
            high=df["high"],
            low=df["low"],
            close=df["close"],
            volume=df["volume"],
            length=self.period,
        )

        if not mfi.empty:
            logger.debug(f"Текущий MFI: {round(mfi.iloc[-1], 2)}")
            mfi_dto = MFIState(
                timestamp=candle.timestamp,
                mfi_value=float(mfi.iloc[-1]),
            )
            self.states.append(mfi_dto)

        if len(self.states) < self.period:
            return SignalType.WAIT

        last_mfi = self.states[-1].mfi_value

        if last_mfi < self.oversold:
            return SignalType.SELL
        elif last_mfi > self.overbought:
            return SignalType.BUY
        return SignalType.WAIT

    def load_state(self, data: Dict[str, Any]) -> None:
        for state_dict in data.get("states", []):
            state = MFIState(**state_dict)
            self.states.append(state)

        for candle_dict in data.get("candles", []):
            candle = Candle(**candle_dict)
            self.candles.append(candle)

    def dump_state(self) -> Dict[str, Any]:
        """
        Сохраняет текущее состояние стратегии.
        """
        return {
            "states": [state.model_dump(mode="json") for state in self.states],
            "candles": [candle.model_dump(mode="json") for candle in self.candles],
        }
