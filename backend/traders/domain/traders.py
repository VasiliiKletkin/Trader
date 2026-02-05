import asyncio
import traceback
from collections import deque
from datetime import datetime
from decimal import Decimal
from itertools import islice
from typing import Dict, Generator, Iterator, List, Optional, Tuple

import numpy as np
from django.utils import timezone
from exchange_clients.domain import (
    AbstractExchangeClient,
    ExchangeClientOrder,
    OrderSide,
)
from exchanges.domain import Candle, Timeframe, TradingPair
from risk_managers.domain import (
    AbstractRiskManager,
    PositionCloseReason,
    PositionStatus,
    PositionType,
)
from strategies.domain import (
    AbstractStrategy,
    ArbitrageTraderSignal,
    SignalType,
    TraderSignal,
)

from .schemas import (
    ArbitrageTraderError,
    ArbitrageTraderPosition,
    TraderPosition,
    TraderStatus,
)


class Trader:
    def __init__(
        self,
        trading_pair: TradingPair,
        timeframe: Timeframe,
        exchange_client: AbstractExchangeClient,
        strategy: AbstractStrategy,
        risk_manager: AbstractRiskManager,
        use_fixed_balance: bool = True,
        initial_balance: Decimal = Decimal("100.0"),
        balance: Decimal = Decimal("100.0"),
        check_drawdown: bool = True,
        max_drawdown_pct: Decimal = Decimal("10.0"),
        max_positions_count: int = 1,
        trail_stop_enabled: bool = True,
        create_new_orders: bool = True,
        close_position_by_take_profit: bool = True,
        close_position_by_stop_loss: bool = True,
        close_position_by_strategy: bool = True,
        close_position_by_opposite_signal: bool = True,
        status: TraderStatus = TraderStatus.ENABLED,
    ):
        self.exchange_client = exchange_client
        self.trading_pair = trading_pair
        self.timeframe = timeframe
        self.strategy = strategy
        self.risk_manager = risk_manager
        self.use_fixed_balance = use_fixed_balance
        self.initial_balance = initial_balance
        self.balance = balance
        self.check_drawdown = check_drawdown
        self.max_drawdown_pct = max_drawdown_pct
        self.create_new_orders = create_new_orders
        self.max_positions_count = max_positions_count
        self.trail_stop_enabled = trail_stop_enabled
        self.close_position_by_opposite_signal = close_position_by_opposite_signal
        self.close_position_by_strategy = close_position_by_strategy
        self.close_position_by_take_profit = close_position_by_take_profit
        self.close_position_by_stop_loss = close_position_by_stop_loss
        self.status = status

        self.errors: str = ""

        self.positions: List[TraderPosition] = []
        self.signals: deque[TraderSignal] = deque()

    async def __aenter__(self) -> "Trader":
        await self.exchange_client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.exchange_client.__aexit__(exc_type, exc, tb)

    def get_last_candles(self, count: int) -> List[Candle]:
        """Получает последние count свечей из сигналов."""
        start = max(0, len(self.signals) - count)
        return [
            signal.candle
            for signal in islice(self.signals, start, len(self.signals))
            if signal.candle is not None
        ]

    @property
    def orders(self) -> List[ExchangeClientOrder]:
        return [order for position in self.positions for order in position.orders]

    @property
    def candles(self) -> Generator[Candle, None, None]:
        return (signal.candle for signal in self.signals if signal.candle)

    @property
    def opened_positions(self) -> Generator[TraderPosition, None, None]:
        return (pos for pos in self.positions if not pos.is_closed)

    @property
    def closed_positions(self) -> Generator[TraderPosition, None, None]:
        return (pos for pos in self.positions if pos.is_closed)

    def get_current_balance(self) -> Decimal:
        if self.use_fixed_balance:
            return self.initial_balance
        return self.balance + self.get_pnl()

    async def create_market_order(
        self,
        side: OrderSide,
        amount: Decimal,
        params: Optional[dict] = None,
    ) -> ExchangeClientOrder:
        order = await self.exchange_client.create_market_order(
            trading_pair=self.trading_pair,
            side=side,
            amount=amount,
            params=params or {},
        )
        return order

    def is_drawdown_within_limit(self) -> bool:
        """
        Проверяет, находится ли текущий drawdown в допустимых пределах.
        """
        if not self.check_drawdown or self.use_fixed_balance:
            return True
        allowed_min_balance = self.initial_balance * (1 - self.max_drawdown_pct / 100)
        return self.get_current_balance() >= allowed_min_balance

    def can_open_more_positions(
        self,
    ) -> bool:
        """
        Проверяет, можно ли открыть еще одну позицию (не превышено ли максимальное количество).
        """
        return len(list(self.opened_positions)) < self.max_positions_count

    def can_open_position(
        self,
        signal: TraderSignal,
        price: Decimal,
    ) -> bool:
        if signal.type not in {SignalType.BUY, SignalType.SELL}:
            return False
        if not self.is_drawdown_within_limit():
            return False
        if not self.can_open_more_positions():
            return False
        return True

    async def open_position(
        self,
        signal: TraderSignal,
        price: Decimal,
        timestamp: datetime,
    ) -> Optional[TraderPosition]:
        position_type = (
            PositionType.LONG if signal.type == SignalType.BUY else PositionType.SHORT
        )

        stop_loss = self.risk_manager.get_stop_loss(
            trader=self,
            position_type=position_type,
            price=price,
        )
        take_profit = self.risk_manager.get_take_profit(
            trader=self,
            position_type=position_type,
            price=price,
        )

        amount = self.risk_manager.calculate_position_size(
            trader=self,
            position_type=position_type,
            price=price,
            balance=self.get_current_balance(),
        )
        amount = amount.quantize(Decimal("1e-18"))

        if amount <= Decimal("0"):
            return

        if amount < self.trading_pair.min_amount:
            amount = self.trading_pair.min_amount
        elif amount > self.trading_pair.max_amount:
            amount = self.trading_pair.max_amount

        order = None
        if self.create_new_orders:
            try:
                order = await self.create_market_order(
                    side=(
                        OrderSide.BUY
                        if position_type == PositionType.LONG
                        else OrderSide.SELL
                    ),
                    amount=amount,
                )
            except Exception as e:
                now = timezone.now()
                error_msg = (
                    f"{now}: {type(e).__name__}: "
                    f"Unexpected error in create_market_order: {str(e)}\n"
                )
                self.errors += error_msg
                return None

        position = TraderPosition(
            type=position_type,
            status=PositionStatus.OPENED,
            open_price=order.price if order else price,
            amount=order.amount if order else amount,
            stop_loss=stop_loss,
            opened_at=order.timestamp if order else timestamp,
            take_profit=take_profit,
            recalculated_at=order.timestamp if order else timestamp,
            total_fee=(
                order.fee
                if order
                else (amount * price * (self.trading_pair.fee_percent / Decimal("100")))
            ),
        )
        self.positions.append(position)

        if order:
            position.orders.append(order)
        return position

    async def close_position(
        self,
        position: TraderPosition,
        price: Decimal,
        timestamp: datetime,
        reason: PositionCloseReason,
    ) -> Optional[TraderPosition]:
        order = None
        try:
            if self.create_new_orders:
                order = await self.create_market_order(
                    side=(
                        OrderSide.SELL
                        if position.type == PositionType.LONG
                        else OrderSide.BUY
                    ),
                    amount=position.amount,
                )
        except Exception as e:
            now = timezone.now()
            error_msg = (
                f"{now}: {type(e).__name__}: "
                f"Unexpected error in create_market_order: {str(e)}\n"
            )
            self.errors += error_msg
            return None

        position.status = PositionStatus.CLOSED
        position.closed_at = order.timestamp if order else timestamp
        position.close_price = order.price if order else price
        position.close_reason = reason
        position.total_fee = position.total_fee + (
            order.fee
            if order
            else (
                position.amount
                * price
                * (self.trading_pair.fee_percent / Decimal("100"))
            )
        )

        if order:
            position.orders.append(order)

        return position

    def update_position(
        self,
        position: TraderPosition,
        price: Decimal,
        timestamp: datetime,
    ) -> TraderPosition:
        new_stop_loss = self.risk_manager.get_stop_loss(
            trader=self,
            position_type=position.type,
            price=price,
        )

        # Обновляем stop_loss только если новое значение лучше
        # (ближе к цене входа)
        if new_stop_loss is not None:
            if position.stop_loss is None:
                position.stop_loss = new_stop_loss
            else:
                # Для LONG позиций: новый stop_loss должен быть выше текущего
                # Для SHORT позиций: новый stop_loss должен быть ниже текущего
                if (
                    position.type == PositionType.LONG
                    and new_stop_loss > position.stop_loss
                ):
                    position.stop_loss = new_stop_loss
                elif (
                    position.type == PositionType.SHORT
                    and new_stop_loss < position.stop_loss
                ):
                    position.stop_loss = new_stop_loss

        new_take_profit = self.risk_manager.get_take_profit(
            trader=self,
            position_type=position.type,
            price=price,
        )

        # Обновляем take_profit только если новое значение лучше
        # (дальше от цены входа)
        if new_take_profit is not None:
            if position.take_profit is None:
                position.take_profit = new_take_profit
            else:
                # Для LONG позиций: новый take_profit должен быть выше
                # Для SHORT позиций: новый take_profit должен быть ниже
                if (
                    position.type == PositionType.LONG
                    and new_take_profit > position.take_profit
                ):
                    position.take_profit = new_take_profit
                elif (
                    position.type == PositionType.SHORT
                    and new_take_profit < position.take_profit
                ):
                    position.take_profit = new_take_profit

        position.recalculated_at = timestamp
        return position

    def get_signal(self, candle: Candle) -> TraderSignal:
        return self.strategy.get_signal(trader=self, candle=candle)

    async def handle_opened_positions(
        self,
        signal: TraderSignal,
        price: Decimal,
        timestamp: datetime,
    ) -> None:
        """
        Обновляет и закрывает открытые позиции по сигналу и цене.
        """
        for position in self.opened_positions:
            if self.trail_stop_enabled:
                self.update_position(
                    timestamp=timestamp,
                    position=position,
                    price=price,
                )
            close, reason = self.position_should_be_closed(
                position=position,
                signal=signal,
                price=price,
            )
            if close:
                await self.close_position(
                    position=position,
                    price=price,
                    timestamp=timestamp,
                    reason=reason,
                )

    async def handle_candle(
        self,
        candle: Candle,
    ) -> None:
        try:
            price = candle.close
            timestamp = candle.timestamp
            signal = self.get_signal(candle=candle)
            self.signals.append(signal)
            if self.status not in {TraderStatus.ENABLED, TraderStatus.REBOOTING}:
                return
            await self.handle_opened_positions(
                signal=signal,
                price=price,
                timestamp=timestamp,
            )
            if not self.can_open_position(signal=signal, price=price):
                return
            await self.open_position(
                signal=signal,
                price=price,
                timestamp=timestamp,
            )
        except Exception as e:
            now = timezone.now()
            error_msg = (
                f"{now}: {type(e).__name__}: " f"{str(e)}\n{traceback.format_exc()}\n"
            )
            self.errors += error_msg

    async def check_opened_positions(
        self,
        candle: Candle,
    ) -> None:
        try:
            price = candle.close
            timestamp = candle.timestamp
            signal = self.get_signal(candle=candle)
            if self.status not in {TraderStatus.ENABLED, TraderStatus.REBOOTING}:
                return
            await self.handle_opened_positions(
                signal=signal,
                price=price,
                timestamp=timestamp,
            )
        except Exception as e:
            now = timezone.now()
            error_msg = (
                f"{now}: {type(e).__name__}: " f"{str(e)}\n{traceback.format_exc()}\n"
            )
            self.errors += error_msg

    def position_should_be_closed(
        self,
        position: TraderPosition,
        signal: TraderSignal,
        price: Decimal,
    ) -> Tuple[bool, PositionCloseReason | None]:
        """
        Проверяет, должна ли позиция быть закрыта на основе сигнала и цены.

        Порядок проверок:
        1. SL
        2. TP
        3. Условия стратегии
        4. Противоположный сигнал
        """
        # Проверяем SL
        if self.close_position_by_stop_loss:
            if position.should_be_closed_by_stop_loss(price=price):
                return True, PositionCloseReason.STOP_LOSS

        # Проверяем TP
        if self.close_position_by_take_profit:
            if position.should_be_closed_by_take_profit(price=price):
                return True, PositionCloseReason.TAKE_PROFIT

        # Проверяем условия стратегии
        if self.close_position_by_strategy:
            if self.strategy.position_should_be_closed(
                position=position, signal=signal
            ):
                return True, PositionCloseReason.STRATEGY

        # Проверяем противоположный сигнал
        if self.close_position_by_opposite_signal:
            is_opposite_signal = (
                position.type == PositionType.LONG and signal.type == SignalType.SELL
            ) or (position.type == PositionType.SHORT and signal.type == SignalType.BUY)
            if is_opposite_signal:
                return True, PositionCloseReason.OPPOSITE_SIGNAL

        return False, None

    async def close_all_opened_positions(
        self,
    ):
        for position in self.opened_positions:
            await self.close_position(
                position=position,
                price=position.open_price,
                timestamp=timezone.now(),
                reason=PositionCloseReason.MANUAL,
            )

    async def reboot(
        self,
        candle_iterator: Iterator[Candle],
    ) -> Decimal:
        """
        Пересимулирует трейдера на переданных свечах.
        """
        create_new_orders = self.create_new_orders
        self.create_new_orders = False
        for candle in candle_iterator:
            await self.handle_candle(candle)
        await self.close_all_opened_positions()
        self.create_new_orders = create_new_orders

    def get_pnl(self) -> Decimal:
        return sum((pos.pnl for pos in self.closed_positions))

    def get_roi(self) -> Decimal:
        return self.get_pnl() / self.initial_balance

    def get_pnl_r2(self) -> Decimal:
        """
        Возвращает R² (коэффициент детерминации) для cumulative PnL закрытых позиций.
        R² рассчитывается по линейной регрессии cumulative PnL по времени закрытия позиции.
        Оптимизировано с numpy.
        """
        closed_positions = sorted(self.closed_positions, key=lambda pos: pos.closed_at)
        if len(closed_positions) < 2:
            return Decimal("0.0")

        cumulative_pnl = 0.0
        x = []
        y = []
        for pos in closed_positions:
            cumulative_pnl += float(pos.pnl)
            x.append(pos.closed_at.timestamp())
            y.append(cumulative_pnl)

        x = np.array(x)
        y = np.array(y)

        coeffs = np.polyfit(x, y, 1)
        slope, intercept = coeffs
        y_pred = slope * x + intercept
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0.0

        return Decimal(str(r_squared))

    def get_win_rate(self) -> Decimal:
        closed_positions = list(self.closed_positions)
        if not closed_positions:
            return Decimal("0.0")
        wins = sum(1 for pos in closed_positions if pos.pnl > 0)
        return Decimal(str(wins / len(closed_positions)))

    def get_sharpe_ratio(self) -> Decimal:
        closed_positions = list(self.closed_positions)
        if len(closed_positions) < 2:
            return Decimal("0.0")

        returns = [float(pos.pnl / self.initial_balance) for pos in closed_positions]
        returns_array = np.array(returns)
        avg_return = np.mean(returns_array)
        std_return = np.std(returns_array)

        if std_return == 0:
            return Decimal("0.0")

        sharpe_ratio = (avg_return / std_return) * np.sqrt(252)
        return Decimal(str(sharpe_ratio))

    def get_avg_candles_per_position(self) -> Decimal:
        """
        Возвращает среднее количество свечей на позицию (время удержания).
        """
        closed_positions = list(self.closed_positions)
        if not closed_positions:
            return Decimal("0.0")
        return Decimal(str(len(self.signals) / len(closed_positions)))

    def get_total_positions(self) -> int:
        """
        Возвращает общее количество позиций (открытых + закрытых).
        """
        return len(self.positions)

    def get_avg_pnl_per_position(self) -> Decimal:
        """
        Возвращает средний PnL на позицию.
        """
        closed_positions = list(self.closed_positions)
        if not closed_positions:
            return Decimal("0.0")
        total_pnl = sum(pos.pnl for pos in closed_positions)
        return total_pnl / len(closed_positions)


class ArbitrageTrader:
    """
    Арбитражный трейдер с двумя клиентами бирж.

    Координирует торговлю на двух биржах одновременно для арбитражных стратегий.
    """

    def __init__(
        self,
        trading_pair: TradingPair,
        timeframe: Timeframe,
        first_exchange_client: AbstractExchangeClient,
        second_exchange_client: AbstractExchangeClient,
        strategy: AbstractStrategy,
        risk_manager: AbstractRiskManager,
        use_fixed_balance: bool = True,
        initial_balance: Decimal = Decimal("100.0"),
        balance: Decimal = Decimal("100.0"),
        check_drawdown: bool = True,
        max_drawdown_pct: Decimal = Decimal("10.0"),
        max_positions_count: int = 1,
        create_new_orders: bool = True,
        close_position_by_strategy: bool = True,
        close_position_by_opposite_signal: bool = True,
        status: TraderStatus = TraderStatus.ENABLED,
    ):
        self.first_exchange_client = first_exchange_client
        self.second_exchange_client = second_exchange_client
        self.trading_pair = trading_pair
        self.timeframe = timeframe
        self.strategy = strategy
        self.risk_manager = risk_manager
        self.use_fixed_balance = use_fixed_balance
        self.initial_balance = initial_balance
        self.balance = balance
        self.check_drawdown = check_drawdown
        self.max_drawdown_pct = max_drawdown_pct
        self.create_new_orders = create_new_orders
        self.max_positions_count = max_positions_count
        self.close_position_by_opposite_signal = close_position_by_opposite_signal
        self.close_position_by_strategy = close_position_by_strategy
        self.status = status

        self.errors: List[ArbitrageTraderError] = []
        self.positions: List[ArbitrageTraderPosition] = []
        self.signals: deque[ArbitrageTraderSignal] = deque()

    async def __aenter__(self) -> "ArbitrageTrader":
        await self.first_exchange_client.__aenter__()
        await self.second_exchange_client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.first_exchange_client.__aexit__(exc_type, exc, tb)
        await self.second_exchange_client.__aexit__(exc_type, exc, tb)

    def get_last_candles(self, count: int) -> List[Candle]:
        """Получает последние count свечей из сигналов."""
        start = max(0, len(self.signals) - count)
        return [
            signal.candle
            for signal in islice(self.signals, start, len(self.signals))
            if signal.candle is not None
        ]

    @property
    def candles(self) -> Generator[Candle, None, None]:
        return (signal.candle for signal in self.signals if signal.candle)

    @property
    def opened_positions(self) -> Generator[ArbitrageTraderPosition, None, None]:
        return (pos for pos in self.positions if not pos.is_closed)

    @property
    def closed_positions(self) -> Generator[ArbitrageTraderPosition, None, None]:
        return (pos for pos in self.positions if pos.is_closed)

    def get_current_balance(self) -> Decimal:
        """Вычисляет текущий баланс с учетом открытых позиций."""
        if self.use_fixed_balance:
            return self.balance
        return self.balance + sum(pos.pnl for pos in self.opened_positions if pos.pnl)

    def is_drawdown_within_limit(self) -> bool:
        """Проверяет, находится ли просадка в пределах допустимого."""
        if not self.check_drawdown:
            return True
        current_balance = self.get_current_balance()
        drawdown = (
            (self.initial_balance - current_balance) / self.initial_balance
        ) * 100
        return drawdown <= self.max_drawdown_pct

    def can_open_more_positions(self, signal_type: Optional[SignalType] = None) -> bool:
        """Проверяет, можем ли открыть еще позиции."""
        opened_count = len(list(self.opened_positions))

        if signal_type:
            same_type_count = sum(
                1
                for pos in self.opened_positions
                if PositionType(pos.type) == PositionType.LONG
                and signal_type == SignalType.BUY
                or PositionType(pos.type) == PositionType.SHORT
                and signal_type == SignalType.SELL
            )
            return same_type_count < self.max_positions_count

        return opened_count < self.max_positions_count

    def get_signal(self, candle: Candle) -> ArbitrageTraderSignal:
        """
        Генерирует сигнал на основе свечи.

        Для арбитражного трейдера candle содержит данные с обеих бирж.
        """
        return self.strategy.get_signal(self, candle)

    def get_pnl(self) -> Decimal:
        """Возвращает общий PnL по всем закрытым позициям."""
        return sum(pos.pnl for pos in self.closed_positions if pos.pnl)

    def get_roi(self) -> Decimal:
        """Возвращает ROI (Return on Investment) в процентах."""
        if not self.initial_balance:
            return Decimal("0.0")
        return (self.get_pnl() / self.initial_balance) * 100

    def get_total_positions(self) -> int:
        """Возвращает общее количество позиций."""
        return len(self.positions)

    def get_avg_pnl_per_position(self) -> Decimal:
        """Возвращает средний PnL на позицию."""
        closed_positions = list(self.closed_positions)
        if not closed_positions:
            return Decimal("0.0")
        total_pnl = sum(pos.pnl for pos in closed_positions if pos.pnl)
        return total_pnl / len(closed_positions)

    def can_open_position(
        self,
        signal: ArbitrageTraderSignal,
    ) -> bool:
        """Проверяет, можно ли открыть позицию."""
        if (
            signal.first_type == SignalType.WAIT
            or signal.second_type == SignalType.WAIT
        ):
            return False
        if not self.is_drawdown_within_limit():
            return False
        if not self.can_open_more_positions():
            return False
        return True

    async def create_market_order(
        self,
        exchange_client: AbstractExchangeClient,
        side: OrderSide,
        amount: Decimal,
        params: Optional[dict] = None,
    ) -> ExchangeClientOrder:
        """Создаёт рыночный ордер на указанной бирже."""
        order = await exchange_client.create_market_order(
            trading_pair=self.trading_pair,
            side=side,
            amount=amount,
            params=params or {},
        )
        return order

    async def open_position(
        self,
        signal: ArbitrageTraderSignal,
    ) -> Optional[ArbitrageTraderPosition]:
        """
        Открывает арбитражную позицию на обеих биржах.

        Для арбитража открываем противоположные позиции:
        - first_type определяет позицию на первой бирже
        - second_type определяет позицию на второй бирже
        """
        first_position_type = (
            PositionType.LONG
            if signal.first_type == SignalType.BUY
            else PositionType.SHORT
        )
        second_position_type = (
            PositionType.LONG
            if signal.second_type == SignalType.BUY
            else PositionType.SHORT
        )

        # Основной тип позиции - по первой бирже
        main_position_type = first_position_type

        amount = self.risk_manager.calculate_position_size(
            trader=self,
            position_type=main_position_type,
            price=signal.first_price,
            balance=self.get_current_balance(),
        )
        amount = amount.quantize(Decimal("1e-18"))

        if amount <= Decimal("0"):
            return None

        if amount < self.trading_pair.min_amount:
            amount = self.trading_pair.min_amount
        elif amount > self.trading_pair.max_amount:
            amount = self.trading_pair.max_amount

        first_order = None
        second_order = None

        if self.create_new_orders:
            first_order, second_order = await asyncio.gather(
                self.create_market_order(
                    exchange_client=self.first_exchange_client,
                    side=(
                        OrderSide.BUY
                        if first_position_type == PositionType.LONG
                        else OrderSide.SELL
                    ),
                    amount=amount,
                ),
                self.create_market_order(
                    exchange_client=self.second_exchange_client,
                    side=(
                        OrderSide.BUY
                        if second_position_type == PositionType.LONG
                        else OrderSide.SELL
                    ),
                    amount=amount,
                ),
            )

        first_fee = (
            first_order.fee
            if first_order
            else (
                amount
                * signal.first_price
                * (self.trading_pair.fee_percent / Decimal("100"))
            )
        )
        second_fee = (
            second_order.fee
            if second_order
            else (
                amount
                * signal.second_price
                * (self.trading_pair.fee_percent / Decimal("100"))
            )
        )

        position = ArbitrageTraderPosition(
            type=main_position_type,
            first_type=first_position_type,
            second_type=second_position_type,
            status=PositionStatus.OPENED,
            amount=first_order.amount if first_order else amount,
            first_open_price=first_order.price if first_order else signal.first_price,
            second_open_price=(
                second_order.price if second_order else signal.second_price
            ),
            opened_at=first_order.timestamp if first_order else signal.timestamp,
            total_fee=first_fee + second_fee,
        )
        self.positions.append(position)

        if first_order:
            position.first_orders.append(first_order)
        if second_order:
            position.second_orders.append(second_order)

        return position

    async def close_position(
        self,
        position: ArbitrageTraderPosition,
        signal: ArbitrageTraderSignal,
        reason: PositionCloseReason,
    ) -> Optional[ArbitrageTraderPosition]:
        """Закрывает арбитражную позицию на обеих биржах."""
        first_order = None
        second_order = None

        if self.create_new_orders:
            first_order, second_order = await asyncio.gather(
                self.create_market_order(
                    exchange_client=self.first_exchange_client,
                    side=(
                        OrderSide.SELL
                        if position.first_type == PositionType.LONG
                        else OrderSide.BUY
                    ),
                    amount=position.amount,
                ),
                self.create_market_order(
                    exchange_client=self.second_exchange_client,
                    side=(
                        OrderSide.SELL
                        if position.second_type == PositionType.LONG
                        else OrderSide.BUY
                    ),
                    amount=position.amount,
                ),
            )

        position.status = PositionStatus.CLOSED
        position.closed_at = first_order.timestamp if first_order else signal.timestamp
        position.first_close_price = (
            first_order.price if first_order else signal.first_price
        )
        position.second_close_price = (
            second_order.price if second_order else signal.second_price
        )
        position.close_reason = reason

        first_fee = (
            first_order.fee
            if first_order
            else (
                position.amount
                * signal.first_price
                * (self.trading_pair.fee_percent / Decimal("100"))
            )
        )
        second_fee = (
            second_order.fee
            if second_order
            else (
                position.amount
                * signal.second_price
                * (self.trading_pair.fee_percent / Decimal("100"))
            )
        )
        position.total_fee = position.total_fee + first_fee + second_fee

        if first_order:
            position.first_orders.append(first_order)
        if second_order:
            position.second_orders.append(second_order)

        return position

    def position_should_be_closed(
        self,
        position: ArbitrageTraderPosition,
        signal: ArbitrageTraderSignal,
    ) -> Tuple[bool, Optional[PositionCloseReason]]:
        """
        Проверяет, должна ли арбитражная позиция быть закрыта.

        Порядок проверок:
        1. Условия стратегии (спред вернулся к норме)
        2. Противоположный сигнал
        """
        # Проверяем условия стратегии
        if self.close_position_by_strategy:
            if self.strategy.position_should_be_closed(
                position=position, signal=signal
            ):
                return True, PositionCloseReason.STRATEGY

        # Проверяем противоположный сигнал
        if self.close_position_by_opposite_signal:
            is_opposite_signal = (
                position.first_type == PositionType.LONG
                and signal.first_type == SignalType.SELL
            ) or (
                position.first_type == PositionType.SHORT
                and signal.first_type == SignalType.BUY
            )
            if is_opposite_signal:
                return True, PositionCloseReason.OPPOSITE_SIGNAL

        return False, None

    async def handle_opened_positions(
        self,
        signal: ArbitrageTraderSignal,
    ) -> None:
        """Обрабатывает открытые позиции - проверяет условия закрытия."""
        for position in list(self.opened_positions):
            close, reason = self.position_should_be_closed(
                position=position,
                signal=signal,
            )
            if close:
                await self.close_position(
                    position=position,
                    signal=signal,
                    reason=reason,
                )

    async def handle_candle(
        self,
        candle: Candle,
    ) -> None:
        """
        Обрабатывает свечу для арбитражного трейдера.

        1. Генерирует сигнал на основе спреда между биржами
        2. Проверяет и закрывает открытые позиции при необходимости
        3. Открывает новые позиции при наличии сигнала
        """
        try:
            signal = self.get_signal(candle=candle)
            self.signals.append(signal)

            if self.status not in {TraderStatus.ENABLED, TraderStatus.REBOOTING}:
                return

            await self.handle_opened_positions(signal=signal)

            if not self.can_open_position(signal=signal):
                return

            await self.open_position(signal=signal)
        except Exception as e:
            now = timezone.now()
            self.errors.append(
                ArbitrageTraderError(
                    timestamp=now,
                    message=str(e),
                    type=type(e).__name__,
                    traceback=traceback.format_exc(),
                )
            )

    async def check_opened_positions(
        self,
        candle: Candle,
    ) -> None:
        """
        Проверяет открытые позиции без открытия новых.

        Используется для проверки условий закрытия позиций
        без генерации новых сигналов на открытие.
        """
        try:
            signal = self.get_signal(candle=candle)
            if self.status not in {TraderStatus.ENABLED, TraderStatus.REBOOTING}:
                return
            await self.handle_opened_positions(signal=signal)
        except Exception as e:
            now = timezone.now()
            self.errors.append(
                ArbitrageTraderError(
                    timestamp=now,
                    message=str(e),
                    type=type(e).__name__,
                    traceback=traceback.format_exc(),
                )
            )

    async def close_all_opened_positions(self) -> None:
        """Закрывает все открытые позиции."""
        if not self.signals:
            return
        last_signal = self.signals[-1]
        for position in list(self.opened_positions):
            await self.close_position(
                position=position,
                signal=last_signal,
                reason=PositionCloseReason.MANUAL,
            )

    async def reboot(
        self,
        candle_iterator: Iterator[Candle],
    ) -> None:
        """Пересимулирует трейдера на переданных свечах."""
        create_new_orders = self.create_new_orders
        self.create_new_orders = False
        for candle in candle_iterator:
            await self.handle_candle(candle)
        await self.close_all_opened_positions()
        self.create_new_orders = create_new_orders
