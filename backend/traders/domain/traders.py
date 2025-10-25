from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple
import traceback

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
    PositionType,
    PositionStatus,
)
from strategies.domain import AbstractStrategy, SignalType, TraderSignal
from .schemas import TraderState, TraderPosition


class Trader:
    def __init__(
        self,
        errors: Optional[str],
        last_error: Optional[datetime],
        trading_pair: TradingPair,
        timeframe: Timeframe,
        exchange_client: AbstractExchangeClient,
        strategy: AbstractStrategy,
        risk_manager: AbstractRiskManager,
        initial_balance: Decimal,
        max_drawdown_pct: Decimal,
        max_positions_count: int,
        current_balance: Decimal,
        trail_stop_enabled: bool = False,
        create_new_orders: bool = True,
        close_position_by_take_profit: bool = True,
        close_position_by_stop_loss: bool = True,
        close_position_by_strategy: bool = True,
        close_position_by_opposite_signal: bool = True,
    ):
        self.exchange_client = exchange_client
        self.trading_pair = trading_pair
        self.timeframe = timeframe
        self.strategy = strategy
        self.risk_manager = risk_manager
        self.initial_balance = initial_balance
        self.max_drawdown_pct = max_drawdown_pct
        self.create_new_orders = create_new_orders
        self.max_positions_count = max_positions_count
        self.trail_stop_enabled = trail_stop_enabled
        self.close_position_by_opposite_signal = close_position_by_opposite_signal
        self.close_position_by_strategy = close_position_by_strategy
        self.close_position_by_take_profit = close_position_by_take_profit
        self.close_position_by_stop_loss = close_position_by_stop_loss
        self.current_balance = current_balance

        self.errors: str = errors if errors else ""
        self.last_error: Optional[datetime] = last_error

        self.orders: List[ExchangeClientOrder] = []
        self.positions: List[TraderPosition] = []
        self.positions_map: Dict[int, List[str]] = {}

        self.states: List[TraderState] = []

    async def __aenter__(self) -> "Trader":
        await self.exchange_client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.exchange_client.__aexit__(exc_type, exc, tb)

    @property
    def opened_positions(self):
        return (pos for pos in self.positions if not pos.is_closed)

    @property
    def signals(self) -> List[TraderSignal]:
        return [state.signal for state in self.states]

    @property
    def candles(self) -> List[Candle]:
        return [state.candle for state in self.states]

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
        self.orders.append(order)
        return order

    async def can_open_position(
        self,
        signal: TraderSignal,
        price: Decimal,
    ) -> bool:
        if signal.type not in {SignalType.BUY, SignalType.SELL}:
            return False
        if not await self.check_drawdown_limit(
            self.current_balance, self.initial_balance
        ):
            return False
        if not await self.check_max_opened_positions(list(self.opened_positions)):
            return False
        return True

    async def check_max_opened_positions(
        self,
        opened_positions: List[TraderPosition],
    ) -> bool:
        return len(opened_positions) < self.max_positions_count

    async def check_drawdown_limit(
        self, current_balance: Decimal, initial_balance: Decimal
    ) -> bool:
        try:
            allowed_min_balance = initial_balance * (
                1 - Decimal(str(self.max_drawdown_pct)) / Decimal("100")
            )
            return current_balance >= allowed_min_balance
        except (InvalidOperation, TypeError):
            return False

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
            balance=self.current_balance,
        )
        amount = amount.quantize(Decimal("1e-18"))

        if amount <= Decimal("0"):
            return

        if amount < self.trading_pair.min_amount:
            amount = self.trading_pair.min_amount

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
                amount = order.amount
                price = order.price
                timestamp = order.timestamp
            except Exception as e:
                now = timezone.now()
                self.errors += f"{now}: {type(e).__name__}: Unexpected error in create_market_order: {str(e)}\n"
                return None

        position = TraderPosition(
            type=position_type,
            status=PositionStatus.OPENED,
            open_price=price,
            amount=amount,
            stop_loss=stop_loss,
            opened_at=timestamp,
            take_profit=take_profit,
            recalculated_at=timestamp,
            data=signal.data,
        )
        self.positions.append(position)
        self.positions_map.setdefault(id(position), [])

        if order:
            self.positions_map[id(position)].append(order.exchange_order_id)
        return position

    async def close_position(
        self,
        position: TraderPosition,
        price: Decimal,
        timestamp: datetime,
        reason: PositionCloseReason,
    ) -> Optional[TraderPosition]:
        order = None
        if self.create_new_orders:
            order = await self.create_market_order(
                side=(
                    OrderSide.SELL
                    if position.type == PositionType.LONG
                    else OrderSide.BUY
                ),
                amount=position.amount,
            )
            price = order.price
            timestamp = order.timestamp

        position.status = PositionStatus.CLOSED
        position.closed_at = timestamp
        position.close_price = price
        position.close_reason = reason

        if order:
            self.positions_map[id(position)].append(order.exchange_order_id)
        return position

    async def update_position(
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
        return self.strategy.get_signal(self, candle)

    async def handle_candle(
        self,
        candle: Candle,
    ) -> None:
        try:
            price = candle.close
            timestamp = candle.timestamp
            signal = self.get_signal(candle=candle)
            self.states.append(
                TraderState(
                    timestamp=candle.timestamp,
                    candle=candle,
                    signal=signal,
                )
            )
            await self.handle_opened_positions(
                signal=signal,
                price=price,
                timestamp=timestamp,
            )
            if not await self.can_open_position(signal=signal, price=price):
                return
            await self.open_position(
                signal=signal,
                price=price,
                timestamp=timestamp,
            )
        except Exception as error:
            now = timezone.now()
            self.errors += f"{now}: {type(error).__name__}: {str(error)}\n{traceback.format_exc()}\n"
            self.last_error = now

    async def check_opened_positions(
        self,
        candle: Candle,
    ) -> None:
        price = candle.close
        timestamp = candle.timestamp
        try:
            signal = self.get_signal(candle=candle)
            await self.handle_opened_positions(
                signal=signal,
                price=price,
                timestamp=timestamp,
            )
        except Exception as error:
            now = timezone.now()
            self.errors += f"{now}: {type(error).__name__}: {str(error)}\n{traceback.format_exc()}\n"
            self.last_error = now

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
                await self.update_position(
                    timestamp=timestamp,
                    position=position,
                    price=price,
                )
            close, reason = await self.position_should_be_closed(
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

    async def position_should_be_closed(
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
