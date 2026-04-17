import traceback
from collections import deque
from collections.abc import Generator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from itertools import islice

import numpy as np

from core.utils.common import format_pnl
from exchange_clients.domain import (
    ExchangeClientOrder,
    OrderSide,
)
from exchange_clients.domain.base import AbstractExchangeClient
from exchanges.domain import Timeframe, TradingPair
from exchanges.domain.schemas import ExchangeCandle

from ..risk_managers.base import AbstractRiskManager
from ..schemas import (
    PositionCloseReason,
    PositionStatus,
    PositionType,
    SignalType,
    TraderError,
    TraderPosition,
    TraderSignal,
    TraderStatus,
)
from ..strategies.base import AbstractStrategy


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
        candles_lookback_count: int = 1000,
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
        self.candles_lookback_count = candles_lookback_count
        self.trail_stop_enabled = trail_stop_enabled
        self.close_position_by_opposite_signal = close_position_by_opposite_signal
        self.close_position_by_strategy = close_position_by_strategy
        self.close_position_by_take_profit = close_position_by_take_profit
        self.close_position_by_stop_loss = close_position_by_stop_loss
        self.status = status

        self.errors: list[TraderError] = []

        self.positions: list[TraderPosition] = []
        self.signals: deque[TraderSignal] = deque()
        self.candles: deque[ExchangeCandle] = deque(maxlen=candles_lookback_count)

    def get_last_candles(self, count: int) -> list[ExchangeCandle]:
        """Получает последние count свечей."""
        if count <= 0:
            return []
        return list(islice(reversed(self.candles), count))[::-1]

    @property
    def orders(self) -> list[ExchangeClientOrder]:
        return [order for position in self.positions for order in position.orders]

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
        price: Decimal,
    ) -> ExchangeClientOrder:
        return await self.exchange_client.create_market_order(
            trading_pair=self.trading_pair,
            side=side,
            amount=amount,
            price=price,
        )

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
    ) -> bool:
        if signal.type not in {SignalType.BUY, SignalType.SELL}:
            return False
        if not self.is_drawdown_within_limit():
            return False
        return self.can_open_more_positions()

    def _quantize_amount(self, amount: Decimal) -> Decimal:
        """Округление количества до точности биржи."""
        return self.trading_pair.quantize_amount(amount)

    def _quantize_price(self, price: Decimal) -> Decimal:
        """Округление цены до точности биржи."""
        return self.trading_pair.quantize_price(price)

    def _validate_cost(self, amount: Decimal, price: Decimal) -> bool:
        """Проверка стоимости ордера на соответствие лимитам биржи."""
        cost = amount * price
        if self.trading_pair.min_cost and cost < self.trading_pair.min_cost:
            return False
        return not (self.trading_pair.max_cost and cost > self.trading_pair.max_cost)

    async def open_position(
        self,
        signal: TraderSignal,
    ) -> TraderPosition | None:
        price = signal.price
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

        stop_loss = self._quantize_price(stop_loss)
        take_profit = self._quantize_price(take_profit)

        amount = self.risk_manager.calculate_position_size(
            trader=self,
            position_type=position_type,
            price=price,
            balance=self.get_current_balance(),
        )
        amount = self._quantize_amount(amount)

        if amount <= Decimal("0"):
            return None

        if self.trading_pair.min_amount and amount < self.trading_pair.min_amount:
            amount = self.trading_pair.min_amount
        if self.trading_pair.max_amount and amount > self.trading_pair.max_amount:
            amount = self.trading_pair.max_amount

        if not self._validate_cost(amount, price):
            return None

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
                    price=price,
                )
            except Exception as e:
                cost = format_pnl(amount * price)
                self.errors.append(
                    TraderError(
                        timestamp=datetime.now(UTC),
                        message=(
                            f"Ошибка при открытии ордера "
                            f"(symbol={self.trading_pair.symbol}, "
                            f"cost=${cost}): "
                            f"{getattr(e, 'error_message', None) or e}"
                        ),
                        type=getattr(e, "error_type", None) or type(e).__name__,
                        traceback=getattr(e, "error_traceback", None)
                        or traceback.format_exc(),
                    )
                )
                return None

        position = TraderPosition(
            type=position_type,
            status=PositionStatus.OPENED,
            open_price=order.price if order else price,
            amount=order.amount if order else amount,
            open_amount=order.amount if order else amount,
            open_cost=order.cost if order else amount * price,
            stop_loss=stop_loss,
            opened_at=order.timestamp if order else signal.timestamp,
            take_profit=take_profit,
            recalculated_at=None,
            total_fee=(
                order.fee if order else (amount * price * self.trading_pair.taker_fee)
            ),
        )
        self.positions.append(position)

        if order:
            position.orders.append(order)
        return position

    async def close_position(
        self,
        position: TraderPosition,
        signal: TraderSignal,
        reason: PositionCloseReason,
    ) -> TraderPosition | None:
        order = None
        close_amount = position.open_amount or position.amount
        try:
            if self.create_new_orders:
                order = await self.create_market_order(
                    side=(
                        OrderSide.SELL
                        if position.type == PositionType.LONG
                        else OrderSide.BUY
                    ),
                    amount=close_amount,
                    price=signal.price,
                )
        except Exception as e:
            cost = format_pnl(close_amount * signal.price)
            self.errors.append(
                TraderError(
                    timestamp=datetime.now(UTC),
                    message=(
                        f"Ошибка при закрытии ордера "
                        f"(symbol={self.trading_pair.symbol}, "
                        f"cost=${cost}): "
                        f"{getattr(e, 'error_message', None) or e}"
                    ),
                    type=getattr(e, "error_type", None) or type(e).__name__,
                    traceback=getattr(e, "error_traceback", None)
                    or traceback.format_exc(),
                )
            )
            return None

        position.status = PositionStatus.CLOSED
        position.closed_at = order.timestamp if order else signal.timestamp
        position.close_price = order.price if order else signal.price
        position.close_amount = order.amount if order else close_amount
        position.close_cost = order.cost if order else close_amount * signal.price
        position.close_reason = reason
        position.total_fee = position.total_fee + (
            order.fee
            if order
            else (close_amount * signal.price * self.trading_pair.taker_fee)
        )

        if order:
            position.orders.append(order)

        return position

    def update_position(
        self,
        position: TraderPosition,
        signal: TraderSignal,
    ) -> TraderPosition:
        new_stop_loss = self.risk_manager.get_stop_loss(
            trader=self,
            position_type=position.type,
            price=signal.price,
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
                ) or (
                    position.type == PositionType.SHORT
                    and new_stop_loss < position.stop_loss
                ):
                    position.stop_loss = new_stop_loss

        new_take_profit = self.risk_manager.get_take_profit(
            trader=self,
            position_type=position.type,
            price=signal.price,
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
                ) or (
                    position.type == PositionType.SHORT
                    and new_take_profit < position.take_profit
                ):
                    position.take_profit = new_take_profit

        position.recalculated_at = signal.timestamp
        return position

    def get_signal(self, candle: ExchangeCandle) -> TraderSignal:
        """
        Генерирует сигнал на основе свечи.

        Заменяет последнюю свечу если таймстамп совпадает (формирующаяся свеча),
        иначе добавляет новую.
        """
        # Удаляем старую свечу с тем же таймстампом до генерации сигнала
        if self.candles and self.candles[-1].dt_unix == candle.dt_unix:
            self.candles.pop()

        timestamp = (
            candle.timestamp
            if self.status == TraderStatus.REBOOTING
            else datetime.now(UTC)
        )
        signal = self.strategy.get_signal(trader=self, candle=candle)
        signal.timestamp = timestamp

        self.signals.append(signal)
        self.candles.append(candle)
        return signal

    async def handle_opened_positions(
        self,
        signal: TraderSignal,
    ) -> None:
        """
        Обновляет и закрывает открытые позиции по сигналу и цене.
        """
        for position in self.opened_positions:
            if self.trail_stop_enabled:
                self.update_position(
                    position=position,
                    signal=signal,
                )
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
        candle: ExchangeCandle,
    ) -> None:
        try:
            signal = self.get_signal(candle=candle)
            if self.status not in {TraderStatus.ENABLED, TraderStatus.REBOOTING}:
                return
            await self.handle_opened_positions(signal=signal)
            if not self.can_open_position(signal=signal):
                return
            await self.open_position(signal=signal)
        except Exception as e:
            self.errors.append(
                TraderError(
                    timestamp=datetime.now(UTC),
                    message=getattr(e, "error_message", None) or str(e),
                    type=getattr(e, "error_type", None) or type(e).__name__,
                    traceback=getattr(e, "error_traceback", None)
                    or traceback.format_exc(),
                )
            )

    def position_should_be_closed(
        self,
        position: TraderPosition,
        signal: TraderSignal,
    ) -> tuple[bool, PositionCloseReason | None]:
        """
        Проверяет, должна ли позиция быть закрыта на основе сигнала и цены.

        Порядок проверок:
        1. SL
        2. TP
        3. Условия стратегии
        4. Противоположный сигнал
        """
        # Проверяем SL
        if self.close_position_by_stop_loss and position.should_be_closed_by_stop_loss(
            price=signal.price
        ):
            return True, PositionCloseReason.STOP_LOSS

        # Проверяем TP
        if (
            self.close_position_by_take_profit
            and position.should_be_closed_by_take_profit(price=signal.price)
        ):
            return True, PositionCloseReason.TAKE_PROFIT

        # Проверяем условия стратегии
        if self.close_position_by_strategy and self.strategy.position_should_be_closed(
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

    async def close_all_opened_positions(self) -> None:
        if not self.signals:
            return
        last_signal = self.signals[-1]
        for position in self.opened_positions:
            await self.close_position(
                position=position,
                signal=last_signal,
                reason=PositionCloseReason.MANUAL,
            )

    async def reboot(
        self,
        candle_iterator: Iterator[ExchangeCandle],
    ) -> None:
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
        return sum((pos.pnl for pos in self.closed_positions if pos.pnl), Decimal("0"))

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
        x_list: list[float] = []
        y_list: list[float] = []
        for pos in closed_positions:
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
        pnl = sum((pos.pnl for pos in closed_positions if pos.pnl), Decimal("0"))
        return pnl / len(closed_positions)
