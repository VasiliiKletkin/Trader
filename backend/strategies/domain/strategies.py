from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

import pandas as pd
import pandas_ta as ta
from pydantic import BaseModel
from exchanges.domain.schemas import Candle
from loguru import logger

from .base import AbstractStrategy
from .schemas import BrickDTO, SignalType


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
        self.bricks: List[BrickDTO] = []
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

        last_part: List[BrickDTO] = self.bricks[-3:]

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
        self.bricks = [BrickDTO(**brick) for brick in bricks]

    def dump_state(self) -> Dict[str, Any]:
        """
        Сохраняет текущее состояние стратегии (для восстановления при перезапуске).
        """
        return {
            "bricks": [brick.model_dump(mode="json") for brick in self.bricks],
        }

    @property
    def last_brick(self) -> Optional[BrickDTO]:
        return self.bricks[-1] if self.bricks else None

    def add_new_brick(self, brick: BrickDTO) -> None:
        """
        Добавляет новый кирпич в список bricks.

        Args:
            brick (BrickDTO): Кирпич, который необходимо добавить.
        """
        self.bricks.append(brick)

    def _update_wick_min(self, wick: Optional[Decimal], price: Decimal) -> Decimal:
        return price if wick is None else min(wick, price)

    def _update_wick_max(self, wick: Optional[Decimal], price: Decimal) -> Decimal:
        return price if wick is None else max(wick, price)

    def build_bricks(self, candle: Candle) -> List[BrickDTO]:
        """
        Строит новые кирпичи на основе поступившей свечи.

        Args:
            candle (Candle): Входящая свеча.

        Returns:
            List[BrickDTO]: Список новых кирпичей (может быть пустым).
        """
        price = candle.close
        dt = candle.timestamp
        new_bricks = []

        brick_size_up = price / Decimal("100") * Decimal(self.threshold_up)
        brick_size_down = price / Decimal("100") * Decimal(self.threshold_down)
        last = self.last_brick

        if last is None:
            logger.debug("Первый кирпич строится.")
            brick = BrickDTO(timestamp=dt, type="first", open=price, close=price)
            self.add_new_brick(brick)
            return [brick]

        def create(
            direction: str, count: int, wick: Optional[Decimal] = None
        ) -> List[BrickDTO]:
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
    ) -> List[BrickDTO]:
        """
        Создаёт список кирпичей по направлению и количеству.

        Args:
            dt (datetime): Временная метка для кирпичей.
            direction (str): Направление ('up' или 'down').
            count (int): Количество кирпичей.
            brick_size (Decimal): Размер одного кирпича.
            wick (Optional[Decimal]): Верхняя или нижняя тень.

        Returns:
            List[BrickDTO]: Список созданных кирпичей.
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

            brick = BrickDTO(
                timestamp=dt,
                type=direction,
                open=new_open,
                close=new_close,
                low=wick,
                high=wick,
            )
            new_bricks.append(brick)
        return new_bricks


class MFRState(BaseModel):
    candle: Candle
    mfi_value: Decimal


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

        self.states: Dict[datetime, MFRState] = {}
        # Максимальное количество состояний для хранения в памяти
        self.max_states = max(period * 2, 100)

    @property
    def candles(self) -> List[Candle]:
        """
        Возвращает список свечей, используемых для расчёта MFI.
        """
        return [self.states[dt].candle for dt in sorted(self.states.keys())]

    @property
    def mfi_values(self) -> List[MFRState]:
        """
        Возвращает список состояний MFI, отсортированных по времени.
        """
        return [self.states[dt] for dt in sorted(self.states.keys())]

    def _cleanup_old_states(self) -> None:
        """
        Удаляет старые состояния, оставляя только необходимые для расчётов.
        """
        if len(self.states) <= self.max_states:
            return

        sorted_timestamps = sorted(self.states.keys())
        # Оставляем только последние max_states состояний
        timestamps_to_remove = sorted_timestamps[:-self.max_states]

        for timestamp in timestamps_to_remove:
            del self.states[timestamp]

        logger.debug(
            f"Удалено {len(timestamps_to_remove)} старых состояний MFI"
        )

    def handle_candle(self, candle: Candle) -> None:
        """
        Обрабатывает поступающую свечу и пересчитывает MFI.
        """
        logger.debug(f"Получена свеча: {candle}")

        timestamp = candle.timestamp

        if timestamp in self.states:
            logger.warning(
                f"Свеча с временной меткой {timestamp} уже обработана."
            )
            return

        # Добавляем новую свечу в состояния
        self.states[timestamp] = MFRState(candle=candle, mfi_value=Decimal(0))

        # Если свечей недостаточно для расчёта MFI, выходим
        if len(self.candles) < self.period:
            logger.debug(
                f"Недостаточно данных для расчёта MFI: "
                f"{len(self.candles)}/{self.period}"
            )
            return

        # Создаём DataFrame из последних свечей для расчёта MFI
        recent_candles = self.candles[-self.period:]
        df = pd.DataFrame(
            [c.model_dump(exclude={"dt_unix"}) for c in recent_candles],
            dtype="float64",
        )
        numeric_cols = ["high", "low", "close", "open", "volume"]

        for col in numeric_cols:
            df[col] = df[col].astype("float64")

        # Рассчитываем MFI
        mfi = ta.mfi(
            high=df["high"],
            low=df["low"],
            close=df["close"],
            volume=df["volume"],
            length=self.period,
        )

        if not mfi.empty and pd.notna(mfi.iloc[-1]):
            mfi_value = Decimal(str(mfi.iloc[-1]))
            logger.debug(f"Текущий MFI: {round(float(mfi_value), 2)}")
            # Обновляем значение MFI для текущей свечи
            self.states[timestamp] = MFRState(
                candle=candle, mfi_value=mfi_value
            )
        else:
            logger.warning("Не удалось рассчитать MFI")
            # Удаляем состояние, если не удалось рассчитать MFI
            del self.states[timestamp]

        # Очищаем старые состояния для экономии памяти
        self._cleanup_old_states()

    def get_current_mfi(self) -> Optional[Decimal]:
        """
        Возвращает текущее значение MFI или None, если данных недостаточно.
        """
        if not self.mfi_values:
            return None
        return self.mfi_values[-1].mfi_value

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
            logger.debug(
                f"MFI {float(current_mfi):.2f} < {self.oversold} - BUY"
            )
            return SignalType.BUY  # При перепроданности покупаем
        elif current_mfi > self.overbought:
            logger.debug(
                f"MFI {float(current_mfi):.2f} > {self.overbought} - SELL"
            )
            return SignalType.SELL  # При перекупленности продаём
        
        logger.debug("MFI в нейтральной зоне - WAIT")
        return SignalType.WAIT

    def get_strategy_info(self) -> Dict[str, Any]:
        """
        Возвращает информацию о текущем состоянии стратегии.
        """
        current_mfi = self.get_current_mfi()
        return {
            "strategy_type": "MFI",
            "period": self.period,
            "overbought": self.overbought,
            "oversold": self.oversold,
            "states_count": len(self.states),
            "current_mfi": float(current_mfi) if current_mfi else None,
            "max_states": self.max_states,
        }

    def load_state(self, data: Dict[str, Any]) -> None:
        """
        Загружает сохранённое состояние стратегии.
        """
        try:
            mfi_states = data.get("mfi_states", [])
            loaded_count = 0
            
            for state_dict in mfi_states:
                try:
                    state = MFRState(**state_dict)
                    self.states[state.candle.timestamp] = state
                    loaded_count += 1
                except Exception as e:
                    logger.warning(f"Ошибка загрузки состояния MFI: {e}")
                    continue
            
            logger.info(f"Загружено {loaded_count} состояний MFI")
            
            # Очищаем старые состояния после загрузки
            self._cleanup_old_states()
            
        except Exception as e:
            logger.error(f"Ошибка загрузки состояния стратегии MFI: {e}")
            self.states = {}

    def dump_state(self) -> Dict[str, Any]:
        """
        Сохраняет текущее состояние стратегии.
        """
        try:
            mfi_states = [
                state.model_dump(mode="json") for state in self.states.values()
            ]
            
            state_data = {
                "mfi_states": mfi_states,
                "strategy_info": self.get_strategy_info(),
                "timestamp": datetime.now().isoformat(),
            }
            
            logger.debug(f"Сохранено {len(mfi_states)} состояний MFI")
            return state_data
            
        except Exception as e:
            logger.error(f"Ошибка сохранения состояния стратегии MFI: {e}")
            return {
                "mfi_states": [],
                "strategy_info": self.get_strategy_info(),
                "timestamp": datetime.now().isoformat(),
            }
