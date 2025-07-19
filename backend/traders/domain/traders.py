from typing import Dict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from narwhals import List
from risk_managers.domain import DomainTraderPosition, DomainPositionType
from traders.domain.orders import ExchangeOrder, OrderSide
from traders.domain.schemas import PositionStatusDomain
from risk_managers.domain.base import AbstractRiskManager
from strategies.domain import AbstractStrategy, SignalTypeDomain
from exchanges.domain import AbstractExchangeClient
from exchanges.domain.schemas import (
    CandleDomain, TradingPairDomain, TimeFrameDomain
)


class TraderDomain:
    def __init__(
        self,
        exchange_client: AbstractExchangeClient,
        trading_pair: TradingPairDomain,
        timeframe: TimeFrameDomain,
        strategy: AbstractStrategy,
        risk_manager: AbstractRiskManager,
        initial_balance: Decimal,
        max_drawdown_pct: Decimal,
        max_positions_count: int,
        current_balance: Decimal,
        orders: List[ExchangeOrder],
        positions: List[DomainTraderPosition],
        candles: List[CandleDomain],
        trail_stop_enabled: bool = False,
    ):
        self.exchange_client = exchange_client
        self.trading_pair = trading_pair
        self.timeframe = timeframe
        self.strategy = strategy
        self.risk_manager = risk_manager
        self.initial_balance = initial_balance
        self.max_drawdown_pct = max_drawdown_pct
        self.max_positions_count = max_positions_count
        self.trail_stop_enabled = trail_stop_enabled
        self.current_balance = current_balance
        self.candles = candles
        self.orders = orders
        self.positions = positions

        # self.strategy.load_data(data=data, candles=self.candles)
        # self.risk_manager.load_data(data=data, candles=self.candles)

    def opened_positions(self):
        return (pos for pos in self.positions if pos.status == PositionStatusDomain.OPENED)

    def create_market_order(
        self,
        trading_pair: TradingPairDomain,
        side: OrderSide,
        amount: Decimal,
        price: Optional[Decimal] = None,
        params: Optional[dict] = None,
    ) -> ExchangeOrder:

        order = self.exchange_client.create_market_order(
            trading_pair=trading_pair,
            side=side,
            amount=amount,
            price=price,
            params=params,
        )
        self.orders.append(order)
        return order

    def can_open_position(
        self,
        signal: SignalType,
        price: Decimal,
    ) -> bool:
        if signal not in {SignalType.BUY, SignalType.SELL}:
            return False
        if not self.check_drawdown_limit(self.current_balance, self.initial_balance):
            return False
        if not self.check_max_opened_positions(self.opened_positions):
            return False
        return True

    def check_max_opened_positions(
        self,
        opened_positions: List[Any],
    ) -> bool:
        return len(opened_positions) < self.max_positions_count

    def check_drawdown_limit(
        self, current_balance: Decimal, initial_balance: Decimal
    ) -> bool:
        try:
            allowed_min_balance = initial_balance * (
                1 - Decimal(str(self.max_drawdown_pct)) / Decimal("100")
            )
            return current_balance >= allowed_min_balance
        except (InvalidOperation, TypeError):
            return False

    def open_position(
        self,
        signal: SignalType,
        price: Decimal,
        create_order: bool = True,
        timestamp: Optional[datetime] = None,
    ) -> Optional[TraderPosition]:

        position_type = (
            PositionType.LONG if signal == SignalType.BUY else PositionType.SHORT
        )

        stop_loss = self.risk_manager.get_stop_loss(
            position_type=position_type,
            price=price,
        )
        take_profit = self.risk_manager.get_take_profit(
            position_type=position_type,
            price=price,
        )

        position_size = self.risk_manager.calculate_position_size(
            position_type=position_type,
            price=price,
            balance=self.current_balance,
        )

        if position_size <= 0:
            return

        order = None
        if create_order:
            order = self.create_market_order(
                trading_pair=self.trading_pair,
                side=(
                    OrderSide.BUY
                    if position_type == PositionType.LONG
                    else OrderSide.SELL
                ),
                price=price,
                amount=position_size,
            )

        if order:
            amount = order.amount or position_size
            open_price = order.price or price

        position = TraderPosition(
            type=position_type,
            status=PositionStatus.OPENED,
            open_price=open_price,
            amount=amount,
            stop_loss=stop_loss,
            opened_at=timestamp,
            take_profit=take_profit,
        )
        self.positions.append(position)
        return position

    def close_position(
        self,
        position: TraderPosition,
        price: Decimal,
        create_order: bool = True,
        timestamp: Optional[datetime] = None,
    ) -> TraderPosition:

        order = None
        if create_order:
            order = self.create_market_order(
                trading_pair=self.trading_pair,
                side=(
                    OrderSide.SELL
                    if position.type == PositionType.LONG
                    else OrderSide.BUY
                ),
                amount=position.amount,
                price=price,
            )
        close_price = order.price if order else price
        position.status = PositionStatus.CLOSED
        position.closed_at = timestamp
        position.close_price = close_price
        return position

    def update_position(
        self,
        position: TraderPosition,
        price: Decimal,
        timestamp: Optional[datetime] = None,
    ) -> TraderPosition:

        new_stop_loss = self.risk_manager.get_stop_loss(
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

        position.updated_at = timestamp or timezone.now()
        return position

    def handle_candle(
        self,
        candle: Candle,
        create_order: bool = True,
    ) -> None:

        # self.check_opened_positions(candle=candle, create_order=create_order)

        self.strategy.handle_candle(candle=candle)
        signal = self.strategy.get_signal()

        if not self.can_open_position(signal=signal, price=candle.close):
            return

        opened_position = self.open_position(
            signal=signal,
            price=candle.close,
            create_order=create_order,
            timestamp=candle.timestamp,
        )
        self.opened_positions.append(opened_position)

    def check_opened_positions(
        self,
        candle: Candle,
        create_order: bool = True,
    ) -> List[TraderPosition]:

        price = candle.close
        self.strategy.handle_candle(candle=candle)
        signal = self.strategy.get_signal()

        for position in self.opened_positions:
            if self.trail_stop_enabled:
                position = self.update_position(
                    position=position,
                    price=price,
                )
            if position.should_be_closed(signal=signal, price=price):
                position = self.close_position(
                    position=position,
                    price=price,
                    create_order=create_order,
                    timestamp=candle.timestamp,
                )
