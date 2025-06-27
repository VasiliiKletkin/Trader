from collections import deque
from typing import Any, Dict, Optional

import pandas as pd
import pandas_ta as ta
from exchanges.domain.schemas import CandleDTO
from loguru import logger
from strategies.domain.strategies.base import AbstractStrategy, SignalType


class MFIStrategy(AbstractStrategy):
    """
    Стратегия на основе индикатора Money Flow Index (MFI), реализованная через pandas_ta.

    Аргументы:
    - period: Период MFI.
    - overbought: Уровень перекупленности.
    - oversold: Уровень перепроданности.
    """

    def __init__(
        self,
        period: int = 14,
        overbought: float = 70.0,
        oversold: float = 30.0,
        **kwargs,
    ) -> None:
        self.period = period
        self.overbought = overbought
        self.oversold = oversold

        self.mfi: Optional[pd.Series] = None
        self.candles: deque[CandleDTO] = deque(maxlen=self.period)

    def handle_candle(self, candle: CandleDTO) -> None:
        """
        Обрабатывает поступающую свечу и пересчитывает MFI.
        """
        logger.debug(f"Получена свеча: {candle}")
        self.candles.append(candle)

        if len(self.candles) < self.period:
            self.mfi = None
            return

        self._recalculate_mfi()

    def get_signals(self) -> SignalType:
        """
        Генерирует торговые сигналы на основе последнего значения MFI.
        """
        if self.mfi is None or len(self.mfi) == 0:
            return SignalType.WAIT

        last_mfi = self.mfi.iloc[-1]

        if last_mfi < self.oversold:
            return SignalType.BUY
        elif last_mfi > self.overbought:
            return SignalType.SELL
        return SignalType.WAIT

    def load_data(self, data: Dict[str, Any]) -> None:
        """
        Загружает сохранённое состояние стратегии.
        """
        candle_dicts = data.get("candles", [])
        self.candles = deque((CandleDTO(**c) for c in candle_dicts), maxlen=self.period)

        if len(self.candles) >= self.period:
            self._recalculate_mfi()
        else:
            self.mfi = None

    def dump_data(self) -> Dict[str, Any]:
        """
        Сохраняет текущее состояние стратегии.
        """
        return {"candles": [candle.model_dump(mode="json") for candle in self.candles]}

    def _recalculate_mfi(self) -> None:
        """
        Пересчитывает индикатор MFI с использованием pandas_ta.
        """
        df = pd.DataFrame([c.model_dump() for c in list(self.candles)])

        self.mfi = ta.mfi(
            high=df["high"],
            low=df["low"],
            close=df["close"],
            volume=df["volume"],
            length=self.period,
        )

        logger.debug(f"Текущий MFI (pandas_ta): {self.mfi.iloc[-1]:.2f}")
