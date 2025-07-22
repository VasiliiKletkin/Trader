from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

import pandas as pd
import pandas_ta as ta
from pydantic import BaseModel
from exchanges.domain.schemas import Candle
from loguru import logger

from .base import AbstractStrategy
from .schemas import RenckoBrick, SignalType


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
        self.bricks: List[RenckoBrick] = []
        self._low_wick: Optional[Decimal] = None
        self._high_wick: Optional[Decimal] = None

        logger.info(
            f"RenkoStrategy инициализирована: threshold_up={threshold_up}, threshold_down={threshold_down}"
        )

    def handle_candle(self, candle: Candle) -> None:
        """
        Обрабатывает новую свечу: строит кирпичи и принимает торговое решение.
        Args:
            candle (Candle): Новая входящая свеча.
        """
        logger.debug(f"Обработка свечи: {candle}")
        new_bricks = self.build_bricks(candle)

        if not new_bricks:
            return None

        for brick in new_bricks:
            self.add_new_brick(brick)

    def get_signal(self) -> SignalType:
        """
        Возвращает торговый сигнал на основе последних кирпичей.
        - BUY: 3 подряд вверх
        - SELL: 3 подряд вниз
        - OTHERWISE: WAIT
        """

        if len(self.bricks) < 3:
            return SignalType.WAIT

        last_part: List[RenckoBrick] = self.bricks[-3:]

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
        bricks = data.get("bricks", [])
        self.bricks = [RenckoBrick(**brick) for brick in bricks]

    def dump_state(self) -> Dict[str, Any]:
        """
        Сохраняет текущее состояние стратегии (для восстановления при перезапуске).
        """
        return {
            "bricks": [brick.model_dump(mode="json") for brick in self.bricks],
        }

    @property
    def last_brick(self) -> Optional[RenckoBrick]:
        return self.bricks[-1] if self.bricks else None

    def add_new_brick(self, brick: RenckoBrick) -> None:
        """
        Добавляет новый кирпич в список bricks.

        Args:
            brick (RenckoBrick): Кирпич, который необходимо добавить.
        """
        self.bricks.append(brick)

    def _update_wick_min(self, wick: Optional[Decimal], price: Decimal) -> Decimal:
        return price if wick is None else min(wick, price)

    def _update_wick_max(self, wick: Optional[Decimal], price: Decimal) -> Decimal:
        return price if wick is None else max(wick, price)

    def build_bricks(self, candle: Candle) -> List[RenckoBrick]:
        """
        Строит новые кирпичи на основе поступившей свечи.

        Args:
            candle (Candle): Входящая свеча.

        Returns:
            List[RenckoBrick]: Список новых кирпичей (может быть пустым).
        """
        price = candle.close
        dt = candle.timestamp
        new_bricks = []

        brick_size_up = price / Decimal("100") * Decimal(self.threshold_up)
        brick_size_down = price / Decimal("100") * Decimal(self.threshold_down)
        last = self.last_brick

        if last is None:
            logger.debug("Первый кирпич строится.")
            brick = RenckoBrick(timestamp=dt, type="first", open=price, close=price)
            self.add_new_brick(brick)
            return [brick]

        def create(
            direction: str, count: int, wick: Optional[Decimal] = None
        ) -> List[RenckoBrick]:
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
    ) -> List[RenckoBrick]:
        """
        Создаёт список кирпичей по направлению и количеству.

        Args:
            dt (datetime): Временная метка для кирпичей.
            direction (str): Направление ('up' или 'down').
            count (int): Количество кирпичей.
            brick_size (Decimal): Размер одного кирпича.
            wick (Optional[Decimal]): Верхняя или нижняя тень.

        Returns:
            List[RenckoBrick]: Список созданных кирпичей.
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

            brick = RenckoBrick(
                timestamp=dt,
                type=direction,
                open=new_open,
                close=new_close,
                low=wick,
                high=wick,
            )
            new_bricks.append(brick)
        return new_bricks


class MFIState(BaseModel):
    candle: Candle
    mfi_value: Decimal | None = None


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
        self.state: Dict[datetime, MFIState] = {}

    @property
    def candles(self) -> List[Candle]:
        """
        Возвращает список свечей, используемых для расчёта MFI.
        """
        return [self.state[dt].candle for dt in sorted(self.state.keys())]

    @property
    def mfi_values(self) -> List[Decimal]:
        """
        Возвращает список состояний MFI, отсортированных по времени.
        """
        return [self.state[dt].mfi_value for dt in sorted(self.state.keys())]

    def handle_candle(self, candle: Candle) -> None:
        """
        Обрабатывает поступающую свечу и пересчитывает MFI.
        """
        logger.debug(f"Получена свеча: {candle}")

        timestamp = candle.timestamp

        if timestamp in self.state:
            logger.warning(f"Свеча с временной меткой {timestamp} уже обработана.")
            return

        self.state[timestamp] = MFIState(candle=candle)

        if len(self.candles) < self.period:
            logger.debug(
                f"Недостаточно данных для расчёта MFI: "
                f"{len(self.candles)}/{self.period}"
            )
            return

        df = pd.DataFrame(
            [c.model_dump(exclude={"dt_unix"}) for c in self.candles[-self.period :]],
            dtype="float64",
        )

        for col in ["high", "low", "close", "open", "volume"]:
            df[col] = df[col].astype("float64")

        mfi = ta.mfi(
            high=df["high"],
            low=df["low"],
            close=df["close"],
            volume=df["volume"],
            length=self.period,
        )

        if not mfi.empty:
            mfi_value = Decimal(str(mfi.iloc[-1]))
            logger.debug(f"Текущий MFI: {round(float(mfi_value), 2)}")
            self.state[timestamp] = MFIState(candle=candle, mfi_value=mfi_value)

    def get_current_mfi(self) -> Optional[Decimal]:
        """
        Возвращает текущее значение MFI или None, если данных недостаточно.
        """
        if not self.mfi_values:
            return None
        return self.mfi_values[-1]

    def get_signal(self) -> SignalType:
        """
        Генерирует торговые сигналы на основе последнего значения MFI.
        """
        current_mfi = self.get_current_mfi()

        if current_mfi is None:
            logger.debug("Недостаточно данных для генерации сигнала")
            return SignalType.WAIT

        logger.debug(f"Текущий MFI: {float(current_mfi):.2f}")

        if current_mfi < self.oversold:
            logger.debug(f"MFI {float(current_mfi):.2f} < {self.oversold} - BUY")
            return SignalType.BUY
        elif current_mfi > self.overbought:
            logger.debug(f"MFI {float(current_mfi):.2f} > {self.overbought} - SELL")
            return SignalType.SELL

        logger.debug("MFI в нейтральной зоне - WAIT")
        return SignalType.WAIT

    def load_state(self, data: Dict[str, Any]) -> None:
        mfi_states = data.get("mfi", [])
        for state_dict in mfi_states:
            state = MFIState(**state_dict)
            self.state[state.candle.timestamp] = state

    def dump_state(self) -> Dict[str, Any]:
        """
        Сохраняет текущее состояние стратегии.
        """
        return {
            "mfi": [state.model_dump(mode="json") for state in self.state.values()],
        }
