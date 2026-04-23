import asyncio
import traceback
from collections import deque
from collections.abc import AsyncIterator, Generator
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

from ..risk_managers.base import AbstractArbitrageRiskManager
from ..schemas import (
    ArbitrageCandle,
    ArbitrageTraderError,
    ArbitrageTraderPosition,
    ArbitrageTraderSignal,
    PositionCloseReason,
    PositionStatus,
    PositionType,
    SignalType,
    TraderStatus,
)
from ..strategies.base import AbstractArbitrageStrategy


class ArbitrageTrader:
    """
    Арбитражный трейдер с двумя клиентами бирж.

    Координирует торговлю на двух биржах одновременно для арбитражных стратегий.
    """

    def __init__(
        self,
        left_trading_pair: TradingPair,
        right_trading_pair: TradingPair,
        timeframe: Timeframe,
        left_exchange_client: AbstractExchangeClient,
        right_exchange_client: AbstractExchangeClient,
        strategy: AbstractArbitrageStrategy,
        risk_manager: AbstractArbitrageRiskManager,
        use_fixed_balance: bool = True,
        initial_balance: Decimal = Decimal("100.0"),
        balance: Decimal = Decimal("100.0"),
        check_drawdown: bool = True,
        max_drawdown_pct: Decimal = Decimal("10.0"),
        max_positions_count: int = 1,
        candles_lookback_count: int = 10,
        create_new_orders: bool = True,
        close_position_by_strategy: bool = True,
        close_position_by_opposite_signal: bool = True,
        status: TraderStatus = TraderStatus.ENABLED,
    ):
        self.left_exchange_client = left_exchange_client
        self.right_exchange_client = right_exchange_client
        self.left_trading_pair = left_trading_pair
        self.right_trading_pair = right_trading_pair
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
        self.close_position_by_opposite_signal = close_position_by_opposite_signal
        self.close_position_by_strategy = close_position_by_strategy
        self.status = status

        self.errors: list[ArbitrageTraderError] = []
        self.positions: list[ArbitrageTraderPosition] = []
        self.signals: deque[ArbitrageTraderSignal] = deque()
        self.candles: deque[ArbitrageCandle] = deque(maxlen=candles_lookback_count)

    def get_last_candles(self, count: int) -> list[ArbitrageCandle]:
        """Получает последние count арбитражных свечей."""
        start = max(0, len(self.candles) - count)
        return list(islice(self.candles, start, len(self.candles)))

    @property
    def opened_positions(self) -> Generator[ArbitrageTraderPosition, None, None]:
        return (pos for pos in self.positions if not pos.is_closed)

    @property
    def closed_positions(self) -> Generator[ArbitrageTraderPosition, None, None]:
        return (pos for pos in self.positions if pos.is_closed)

    @property
    def orders(
        self,
    ) -> list[tuple[ExchangeClientOrder, ExchangeClientOrder, ArbitrageTraderPosition]]:
        """Возвращает все ордера в формате (left_order, right_order, position)."""
        result = []
        for position in self.positions:
            for left_order, right_order in zip(
                position.left_orders, position.right_orders
            ):
                result.append((left_order, right_order, position))
        return result

    def get_current_balance(self) -> Decimal:
        """Вычисляет текущий баланс с учетом открытых позиций."""
        if self.use_fixed_balance:
            return self.balance
        return self.balance + sum(pos.pnl for pos in self.opened_positions if pos.pnl)

    def is_drawdown_within_limit(self) -> bool:
        """Проверяет, находится ли просадка в пределах допустимого."""
        if not self.check_drawdown:
            return True
        drawdown = (
            (self.initial_balance - self.get_current_balance()) / self.initial_balance
        ) * 100
        return drawdown <= self.max_drawdown_pct

    def can_open_more_positions(self) -> bool:
        """Проверяет, можем ли открыть еще позиции."""
        return len(list(self.opened_positions)) < self.max_positions_count

    def get_signal(
        self,
        candle: ArbitrageCandle,
    ) -> ArbitrageTraderSignal:
        """
        Генерирует сигнал на основе свечей с двух бирж.

        Заменяет последнюю свечу если таймстамп совпадает (формирующаяся свеча),
        иначе добавляет новую.
        """
        # Удаляем старую свечу с тем же таймстампом до генерации сигнала
        if self.candles and self.candles[-1].left.dt_unix == candle.left.dt_unix:
            self.candles.pop()

        timestamp = (
            candle.timestamp
            if self.status == TraderStatus.REBOOTING
            else datetime.now(UTC)
        )
        signal = self.strategy.get_signal(self, candle)
        signal.timestamp = timestamp

        self.signals.append(signal)
        self.candles.append(candle)
        return signal

    def get_pnl(self) -> Decimal:
        """Возвращает общий PnL по всем закрытым позициям."""
        return sum((pos.pnl for pos in self.closed_positions if pos.pnl), Decimal("0"))

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
        pnl = sum((pos.pnl for pos in closed_positions if pos.pnl), Decimal("0"))
        return pnl / len(closed_positions)

    def get_win_rate(self) -> Decimal:
        """Возвращает долю прибыльных позиций."""
        closed_positions = list(self.closed_positions)
        if not closed_positions:
            return Decimal("0.0")
        wins = sum(1 for pos in closed_positions if pos.pnl > 0)
        return Decimal(str(wins / len(closed_positions)))

    def get_sharpe_ratio(self) -> Decimal:
        """Возвращает коэффициент Шарпа."""
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

    def get_pnl_r2(self) -> Decimal:
        """
        Возвращает R² (коэффициент детерминации) для cumulative PnL.
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

    def get_avg_candles_per_position(self) -> Decimal:
        """Возвращает среднее количество свечей на позицию."""
        closed_positions = list(self.closed_positions)
        if not closed_positions:
            return Decimal("0.0")
        return Decimal(str(len(self.signals) / len(closed_positions)))

    def can_open_position(
        self,
        signal: ArbitrageTraderSignal,
    ) -> bool:
        """Проверяет, можно ли открыть позицию."""
        if signal.left_type == SignalType.WAIT or signal.right_type == SignalType.WAIT:
            return False
        if not self.is_drawdown_within_limit():
            return False
        return self.can_open_more_positions()

    async def create_market_order(
        self,
        exchange_client: AbstractExchangeClient,
        trading_pair: TradingPair,
        side: OrderSide,
        amount: Decimal,
        price: Decimal,
    ) -> ExchangeClientOrder:
        """Создаёт рыночный ордер через AbstractExchangeClient."""
        return await exchange_client.create_market_order(
            trading_pair=trading_pair,
            side=side,
            amount=amount,
            price=price,
        )

    async def open_position(
        self,
        signal: ArbitrageTraderSignal,
    ) -> ArbitrageTraderPosition | None:
        """
        Открывает арбитражную позицию на обеих биржах.

        Для арбитража открываем противоположные позиции:
        - left_type определяет позицию на первой бирже
        - right_type определяет позицию на второй бирже
        """
        left_position_type = (
            PositionType.LONG
            if signal.left_type == SignalType.BUY
            else PositionType.SHORT
        )
        right_position_type = (
            PositionType.LONG
            if signal.right_type == SignalType.BUY
            else PositionType.SHORT
        )

        cost = self.risk_manager.calculate_position_size(
            trader=self,
            position_type=left_position_type,
            price=signal.left_price,
            balance=self.get_current_balance(),
        )
        left_raw = self.left_trading_pair.cost_to_amount(cost, signal.left_price)
        right_raw = self.right_trading_pair.cost_to_amount(cost, signal.right_price)
        left_amount = self.left_trading_pair.fit_amount(left_raw, signal.left_price)
        right_amount = self.right_trading_pair.fit_amount(right_raw, signal.right_price)
        if left_amount is None or right_amount is None:
            return None
        left_cost = self.left_trading_pair.compute_cost(
            left_amount,
            signal.left_price,
        )
        right_cost = self.right_trading_pair.compute_cost(
            right_amount, signal.right_price
        )

        left_order = None
        right_order = None

        if self.create_new_orders:
            left_side = (
                OrderSide.BUY
                if left_position_type == PositionType.LONG
                else OrderSide.SELL
            )
            right_side = (
                OrderSide.BUY
                if right_position_type == PositionType.LONG
                else OrderSide.SELL
            )

            # Параллельная отправка — минимизирует drift спреда между
            # моментами исполнения left и right ордеров.
            left_result, right_result = await asyncio.gather(
                self.create_market_order(
                    exchange_client=self.left_exchange_client,
                    trading_pair=self.left_trading_pair,
                    side=left_side,
                    amount=left_amount,
                    price=signal.left_price,
                ),
                self.create_market_order(
                    exchange_client=self.right_exchange_client,
                    trading_pair=self.right_trading_pair,
                    side=right_side,
                    amount=right_amount,
                    price=signal.right_price,
                ),
                return_exceptions=True,
            )

            left_order = (
                left_result if not isinstance(left_result, BaseException) else None
            )
            right_order = (
                right_result if not isinstance(right_result, BaseException) else None
            )

            if isinstance(left_result, BaseException):
                self.errors.append(
                    ArbitrageTraderError(
                        timestamp=datetime.now(UTC),
                        message=(
                            f"Left ордер не исполнен "
                            f"(symbol={self.left_trading_pair.symbol}, "
                            f"cost={format_pnl(left_cost)}): "
                            f"{getattr(left_result, 'error_message', None) or left_result}"
                        ),
                        type=getattr(left_result, "error_type", None)
                        or type(left_result).__name__,
                        traceback=getattr(left_result, "error_traceback", None)
                        or "".join(
                            traceback.format_exception(
                                type(left_result),
                                left_result,
                                left_result.__traceback__,
                            )
                        ),
                    )
                )
            if isinstance(right_result, BaseException):
                self.errors.append(
                    ArbitrageTraderError(
                        timestamp=datetime.now(UTC),
                        message=(
                            f"Right ордер не исполнен "
                            f"(symbol={self.right_trading_pair.symbol}, "
                            f"cost={format_pnl(right_cost)}): "
                            f"{getattr(right_result, 'error_message', None) or right_result}"
                        ),
                        type=getattr(right_result, "error_type", None)
                        or type(right_result).__name__,
                        traceback=getattr(right_result, "error_traceback", None)
                        or "".join(
                            traceback.format_exception(
                                type(right_result),
                                right_result,
                                right_result.__traceback__,
                            )
                        ),
                    )
                )

            # Обе стороны упали — выходим.
            if left_order is None and right_order is None:
                return None

            # Одна сторона упала — откатываем успешную обратным ордером.
            if left_order is None and right_order is not None:
                try:
                    await self.create_market_order(
                        exchange_client=self.right_exchange_client,
                        trading_pair=self.right_trading_pair,
                        side=(
                            OrderSide.SELL
                            if right_side == OrderSide.BUY
                            else OrderSide.BUY
                        ),
                        amount=right_amount,
                        price=signal.right_price,
                    )
                except Exception as rollback_err:
                    self.errors.append(
                        ArbitrageTraderError(
                            timestamp=datetime.now(UTC),
                            message=f"Откат right ордера не удался: {getattr(rollback_err, 'error_message', None) or rollback_err}",
                            type=getattr(rollback_err, "error_type", None)
                            or type(rollback_err).__name__,
                            traceback=getattr(rollback_err, "error_traceback", None)
                            or traceback.format_exc(),
                        )
                    )
                return None

            if right_order is None and left_order is not None:
                try:
                    await self.create_market_order(
                        exchange_client=self.left_exchange_client,
                        trading_pair=self.left_trading_pair,
                        side=(
                            OrderSide.SELL
                            if left_side == OrderSide.BUY
                            else OrderSide.BUY
                        ),
                        amount=left_amount,
                        price=signal.left_price,
                    )
                except Exception as rollback_err:
                    self.errors.append(
                        ArbitrageTraderError(
                            timestamp=datetime.now(UTC),
                            message=f"Откат left ордера не удался: {getattr(rollback_err, 'error_message', None) or rollback_err}",
                            type=getattr(rollback_err, "error_type", None)
                            or type(rollback_err).__name__,
                            traceback=getattr(rollback_err, "error_traceback", None)
                            or traceback.format_exc(),
                        )
                    )
                return None

        left_fee = (
            left_order.fee
            if left_order
            else left_cost * self.left_trading_pair.taker_fee
        )
        right_fee = (
            right_order.fee
            if right_order
            else right_cost * self.right_trading_pair.taker_fee
        )

        position = ArbitrageTraderPosition(
            left_type=left_position_type,
            right_type=right_position_type,
            status=PositionStatus.OPENED,
            left_open_price=left_order.price if left_order else signal.left_price,
            right_open_price=(right_order.price if right_order else signal.right_price),
            left_open_amount=left_order.amount if left_order else left_amount,
            right_open_amount=right_order.amount if right_order else right_amount,
            left_open_cost=left_order.cost if left_order else left_cost,
            right_open_cost=right_order.cost if right_order else right_cost,
            opened_at=signal.timestamp,
            left_total_fee=left_fee,
            right_total_fee=right_fee,
        )
        self.positions.append(position)

        if left_order:
            position.left_orders.append(left_order)
        if right_order:
            position.right_orders.append(right_order)

        return position

    async def close_position(
        self,
        position: ArbitrageTraderPosition,
        signal: ArbitrageTraderSignal,
        reason: PositionCloseReason,
    ) -> ArbitrageTraderPosition | None:
        """Закрывает арбитражную позицию на обеих биржах."""
        left_order = None
        right_order = None

        if self.create_new_orders:
            left_side = (
                OrderSide.SELL
                if position.left_type == PositionType.LONG
                else OrderSide.BUY
            )
            right_side = (
                OrderSide.SELL
                if position.right_type == PositionType.LONG
                else OrderSide.BUY
            )

            left_amount = position.left_open_amount
            right_amount = position.right_open_amount
            left_cost = self.left_trading_pair.compute_cost(
                left_amount, signal.left_price
            )
            right_cost = self.right_trading_pair.compute_cost(
                right_amount, signal.right_price
            )

            try:
                left_order = await self.create_market_order(
                    exchange_client=self.left_exchange_client,
                    trading_pair=self.left_trading_pair,
                    side=left_side,
                    amount=left_amount,
                    price=signal.left_price,
                )
            except Exception as e:
                self.errors.append(
                    ArbitrageTraderError(
                        timestamp=datetime.now(UTC),
                        message=(
                            f"Left ордер закрытия не исполнен "
                            f"(symbol={self.left_trading_pair.symbol}, "
                            f"cost={format_pnl(left_cost)}): "
                            f"{getattr(e, 'error_message', None) or e}"
                        ),
                        type=getattr(e, "error_type", None) or type(e).__name__,
                        traceback=getattr(e, "error_traceback", None)
                        or traceback.format_exc(),
                    )
                )
                return None

            try:
                right_order = await self.create_market_order(
                    exchange_client=self.right_exchange_client,
                    trading_pair=self.right_trading_pair,
                    side=right_side,
                    amount=right_amount,
                    price=signal.right_price,
                )
            except Exception as e:
                self.errors.append(
                    ArbitrageTraderError(
                        timestamp=datetime.now(UTC),
                        message=(
                            f"Right ордер закрытия не исполнен "
                            f"(symbol={self.right_trading_pair.symbol}, "
                            f"cost={format_pnl(right_cost)}): "
                            f"{getattr(e, 'error_message', None) or e}"
                        ),
                        type=getattr(e, "error_type", None) or type(e).__name__,
                        traceback=getattr(e, "error_traceback", None)
                        or traceback.format_exc(),
                    )
                )
                # Откат left ордера закрытия (возвращаем позицию)
                try:
                    await self.create_market_order(
                        exchange_client=self.left_exchange_client,
                        trading_pair=self.left_trading_pair,
                        side=(
                            OrderSide.BUY
                            if left_side == OrderSide.SELL
                            else OrderSide.SELL
                        ),
                        amount=left_order.amount,
                        price=signal.left_price,
                    )
                except Exception as rollback_err:
                    self.errors.append(
                        ArbitrageTraderError(
                            timestamp=datetime.now(UTC),
                            message=f"Откат left ордера закрытия не удался: {getattr(rollback_err, 'error_message', None) or rollback_err}",
                            type=getattr(rollback_err, "error_type", None)
                            or type(rollback_err).__name__,
                            traceback=getattr(rollback_err, "error_traceback", None)
                            or traceback.format_exc(),
                        )
                    )
                return None

        position.status = PositionStatus.CLOSED
        position.closed_at = left_order.timestamp if left_order else signal.timestamp
        position.left_close_price = (
            left_order.price if left_order else signal.left_price
        )
        position.right_close_price = (
            right_order.price if right_order else signal.right_price
        )
        position.close_reason = reason
        position.left_close_amount = (
            left_order.amount if left_order else position.left_open_amount
        )
        position.right_close_amount = (
            right_order.amount if right_order else position.right_open_amount
        )
        left_close_cost = self.left_trading_pair.compute_cost(
            position.left_open_amount, signal.left_price
        )
        right_close_cost = self.right_trading_pair.compute_cost(
            position.right_open_amount, signal.right_price
        )
        position.left_close_cost = left_order.cost if left_order else left_close_cost
        position.right_close_cost = (
            right_order.cost if right_order else right_close_cost
        )

        left_fee = (
            left_order.fee
            if left_order
            else left_close_cost * self.left_trading_pair.taker_fee
        )
        right_fee = (
            right_order.fee
            if right_order
            else right_close_cost * self.right_trading_pair.taker_fee
        )
        position.left_total_fee += left_fee
        position.right_total_fee += right_fee

        if left_order:
            position.left_orders.append(left_order)
        if right_order:
            position.right_orders.append(right_order)

        return position

    def position_should_be_closed(
        self,
        position: ArbitrageTraderPosition,
        signal: ArbitrageTraderSignal,
    ) -> tuple[bool, PositionCloseReason | None]:
        """
        Проверяет, должна ли арбитражная позиция быть закрыта.

        Порядок проверок:
        1. Условия стратегии (спред вернулся к норме)
        2. Противоположный сигнал
        """
        # Проверяем условия стратегии
        if self.close_position_by_strategy and self.strategy.position_should_be_closed(
            position=position, signal=signal
        ):
            return True, PositionCloseReason.STRATEGY

        # Проверяем противоположный сигнал
        if self.close_position_by_opposite_signal:
            is_opposite_signal = (
                position.left_type == PositionType.LONG
                and signal.left_type == SignalType.SELL
            ) or (
                position.left_type == PositionType.SHORT
                and signal.left_type == SignalType.BUY
            )
            if is_opposite_signal:
                return True, PositionCloseReason.OPPOSITE_SIGNAL

        return False, None

    async def handle_opened_positions(
        self,
        signal: ArbitrageTraderSignal,
    ) -> None:
        """Обрабатывает открытые позиции - проверяет условия закрытия."""
        for position in self.opened_positions:
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
        candle: ArbitrageCandle,
    ) -> None:
        """
        Обрабатывает свечи для арбитражного трейдера.

        1. Генерирует сигнал на основе спреда между биржами
        2. Проверяет и закрывает открытые позиции при необходимости
        3. Открывает новые позиции при наличии сигнала
        """
        try:
            signal = self.get_signal(candle=candle)
            if self.status not in {TraderStatus.ENABLED, TraderStatus.REBOOTING}:
                return
            await self.handle_opened_positions(signal=signal)
            if not self.can_open_position(signal=signal):
                return
            await self.open_position(signal=signal)
        except Exception as e:
            now = datetime.now(UTC)
            self.errors.append(
                ArbitrageTraderError(
                    timestamp=now,
                    message=getattr(e, "error_message", None) or str(e),
                    type=getattr(e, "error_type", None) or type(e).__name__,
                    traceback=getattr(e, "error_traceback", None)
                    or traceback.format_exc(),
                )
            )

    async def close_all_opened_positions(self) -> None:
        """Закрывает все открытые позиции с причиной MANUAL."""
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
        candle_iterator: AsyncIterator[ArbitrageCandle],
    ) -> None:
        """Пересимулирует трейдера на переданных свечах."""
        create_new_orders = self.create_new_orders
        self.create_new_orders = False
        async for candle in candle_iterator:
            await self.handle_candle(candle)
        await self.close_all_opened_positions()
        self.create_new_orders = create_new_orders
