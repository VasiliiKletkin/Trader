from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Generator, Iterator
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

import numpy as np

from core.utils.registry import Registry
from exchanges.domain import Timeframe

from ..schemas import PositionCloseReason, TraderStatus


class TraderRegistry(Registry):
    """Реестр классов Trader."""

    pass


@runtime_checkable
class PositionProtocol(Protocol):
    """Протокол для позиций (Trader и ArbitrageTrader)."""

    @property
    def is_closed(self) -> bool: ...

    @property
    def pnl(self) -> Decimal | None: ...

    closed_at: datetime | None


class AbstractTrader[CandleT, SignalT, PositionT: PositionProtocol, StrategyT](
    ABC,
):
    """
    Абстрактный базовый класс для всех трейдеров.

    Определяет общий интерфейс для Trader и ArbitrageTrader:
    - Управление статусом
    - Работа со свечами и сигналами
    - Открытие/закрытие позиций
    - Расчёт статистики (PnL, ROI, Win Rate и т.д.)
    - Reboot (пересимуляция)
    """

    status: TraderStatus
    timeframe: Timeframe
    strategy: StrategyT
    use_fixed_balance: bool
    initial_balance: Decimal
    create_new_orders: bool
    max_positions_count: int
    positions: list[PositionT]
    signals: deque[SignalT]
    errors: str

    # ==================== Abstract Methods ====================

    @abstractmethod
    async def __aenter__(self) -> "AbstractTrader":
        """Асинхронный вход в контекст."""
        pass

    @abstractmethod
    async def __aexit__(self, exc_type, exc, tb) -> None:
        """Асинхронный выход из контекста."""
        pass

    @abstractmethod
    def get_signal(self, candle: CandleT) -> SignalT:
        """Получает сигнал от стратегии."""
        pass

    @abstractmethod
    def can_open_position(self, signal: SignalT) -> bool:
        """Проверяет, можно ли открыть позицию."""
        pass

    @abstractmethod
    async def open_position(
        self,
        signal: SignalT,
    ) -> PositionT | None:
        """Открывает позицию."""
        pass

    @abstractmethod
    async def close_position(
        self,
        signal: SignalT,
        position: PositionT,
        reason: PositionCloseReason,
    ) -> PositionT | None:
        """Закрывает позицию."""
        pass

    @abstractmethod
    def position_should_be_closed(
        self,
        position: PositionT,
        signal: SignalT,
    ) -> tuple[bool, PositionCloseReason | None]:
        """Проверяет, должна ли позиция быть закрыта."""
        pass

    @abstractmethod
    async def handle_opened_positions(
        self,
        signal: SignalT,
    ) -> None:
        """Обрабатывает открытые позиции."""
        pass

    @abstractmethod
    async def handle_candle(self, candle: CandleT) -> None:
        """Обрабатывает свечу: генерирует сигнал, проверяет позиции."""
        pass

    @abstractmethod
    async def close_all_opened_positions(self) -> None:
        """Закрывает все открытые позиции."""
        pass

    @abstractmethod
    async def reboot(
        self,
        candle_iterator: Iterator[CandleT],
    ) -> None:
        """Пересимулирует трейдера на переданных свечах."""
        pass

    # ==================== Common Properties ====================

    @property
    def opened_positions(
        self,
    ) -> Generator[PositionT, None, None]:
        """Генератор открытых позиций."""
        return (pos for pos in self.positions if not pos.is_closed)

    @property
    def closed_positions(
        self,
    ) -> Generator[PositionT, None, None]:
        """Генератор закрытых позиций."""
        return (pos for pos in self.positions if pos.is_closed)

    @property
    def opened_positions_count(self) -> int:
        """Количество открытых позиций."""
        return sum(1 for _ in self.opened_positions)

    # ==================== Common Methods ====================

    def get_current_balance(self) -> Decimal:
        """Возвращает текущий баланс."""
        if self.use_fixed_balance:
            return self.initial_balance
        return self.initial_balance + self.get_pnl()

    def can_open_more_positions(self) -> bool:
        """Проверяет, можно ли открыть ещё позиции."""
        return self.opened_positions_count < self.max_positions_count

    # ==================== Statistics Methods ====================

    def get_pnl(self) -> Decimal:
        """Суммарный PnL всех закрытых позиций."""
        total = Decimal("0")
        for pos in self.closed_positions:
            if pos.pnl is not None:
                total += pos.pnl
        return total

    def get_roi(self) -> Decimal:
        """ROI = PnL / initial_balance."""
        if self.initial_balance == 0:
            return Decimal("0")
        return self.get_pnl() / self.initial_balance

    def get_total_positions(self) -> int:
        """Общее количество позиций."""
        return len(self.positions)

    def get_win_rate(self) -> Decimal:
        """Процент выигрышных позиций."""
        closed = list(self.closed_positions)
        if not closed:
            return Decimal("0")
        wins = sum(1 for pos in closed if pos.pnl is not None and pos.pnl > 0)
        return Decimal(str(wins / len(closed)))

    def get_pnl_r2(self) -> Decimal:
        """
        Возвращает R² (коэффициент детерминации) для cumulative PnL.
        R² рассчитывается по линейной регрессии cumulative PnL по времени.
        """
        closed_positions = sorted(self.closed_positions, key=lambda pos: pos.closed_at)
        if len(closed_positions) < 2:
            return Decimal("0.0")

        cumulative_pnl = 0.0
        x_list: list[float] = []
        y_list: list[float] = []
        for pos in closed_positions:
            if pos.pnl is not None:
                cumulative_pnl += float(pos.pnl)
            x_list.append(pos.closed_at.timestamp())
            y_list.append(cumulative_pnl)

        x_arr = np.array(x_list)
        y_arr = np.array(y_list)

        coeffs = np.polyfit(x_arr, y_arr, 1)
        slope, intercept = coeffs
        y_pred = slope * x_arr + intercept
        ss_res = np.sum((y_arr - y_pred) ** 2)
        ss_tot = np.sum((y_arr - np.mean(y_arr)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0.0

        return Decimal(str(r_squared))

    def get_sharpe_ratio(self) -> Decimal:
        """Коэффициент Шарпа."""
        closed = list(self.closed_positions)
        if len(closed) < 2:
            return Decimal("0.0")

        returns = []
        for pos in closed:
            if pos.pnl is not None:
                returns.append(float(pos.pnl / self.initial_balance))
            else:
                returns.append(0.0)

        returns_array = np.array(returns)
        avg_return = np.mean(returns_array)
        std_return = np.std(returns_array)

        if std_return == 0:
            return Decimal("0.0")

        sharpe_ratio = (avg_return / std_return) * np.sqrt(252)
        return Decimal(str(sharpe_ratio))

    def get_avg_pnl_per_position(self) -> Decimal:
        """Средний PnL на позицию."""
        closed = list(self.closed_positions)
        if not closed:
            return Decimal("0.0")
        pnl = Decimal("0")
        for pos in closed:
            if pos.pnl is not None:
                pnl += pos.pnl
        return pnl / len(closed)
