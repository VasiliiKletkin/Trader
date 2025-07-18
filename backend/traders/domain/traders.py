from ast import Dict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional, Tuple

from narwhals import List
from backend.risk_managers.domain.schemas import PositionDTO
from risk_managers.domain.base import AbstractRiskManager
from strategies.domain import AbstractStrategy, SignalType
from exchanges.domain import AbstractExchangeClient
from exchanges.domain.schemas import CandleDTO, TradingPairDTO, TimeFrameDTO


class Trader:
    def __init__(
        self,
        exchange_client: AbstractExchangeClient,
        trading_pair: TradingPairDTO,
        timeframe: TimeFrameDTO,
        strategy: AbstractStrategy,
        risk_manager: AbstractRiskManager,
        initial_balance: Decimal,
        max_drawdown_pct: Decimal,
        max_positions_count: int,
        trail_stop_enabled: bool = False,
        data: Optional[Dict[str, Any]] = None,
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

        self.candles: List[CandleDTO] = []

    def can_open_position(
        self,
        signal: SignalType,
        price: Decimal,
    ) -> bool:
        if signal not in {SignalType.BUY, SignalType.SELL}:
            return False
        if not self.check_drawdown_limit(self.balance, self.initial_balance):
            return False
        if not self.check_max_positions(list(self.opened_positions)):
            return False
        return True

    def check_max_positions(
        self,
        opened_positions: List[Any],
    ) -> bool:
        return len(opened_positions) < self.max_positions_count

    def check_drawdown_limit(self, balance: Decimal, initial_balance: Decimal) -> bool:
        try:
            allowed_min_balance = initial_balance * (
                1 - Decimal(str(self.max_drawdown_pct)) / Decimal("100")
            )
            return balance >= allowed_min_balance
        except (InvalidOperation, TypeError):
            return False

    def check_opened_positions(
        self,
        candle: CandleDTO,
        create_order: bool = True,
    ) -> List[PositionDTO]:
        price = candle.close
        self.data = self.strategy.handle_candle(data=self.data, candle=candle)
        self.data, signal = self.strategy.get_signal(self.data)
        self.data = self.update_data(candle=candle)

        for position in positions:
            if self.trail_stop_enabled:
                self.data, position = self.update_position(
                    data=self.data,
                    position=position,
                    price=price,
                )
            if position.should_be_closed(signal=signal, price=price):
                self.data, position = self.close_position(
                    data=self.data,
                    position=position,
                    price=price,
                    create_order=create_order,
                    timestamp=candle.timestamp,
                )

    def open_position(
        self,
        data: Dict[str, Any],
        signal: SignalType,
        price: Decimal,
        create_order: bool = True,
        timestamp: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Открывает позицию на основе сигнала и текущей цены.
        """
        position_type = (
            SignalTypeDTO.LONG if signal == SignalType.BUY else PositionType.SHORT
        )

        data, stop_loss = self.risk_manager.get_stop_loss(
            data=data,
            position_type=position_type,
            price=price,
        )
        data, take_profit = self.risk_manager.get_take_profit(
            data=data,
            position_type=position_type,
            price=price,
        )

        data, position_size = self.risk_manager.calculate_position_size(
            data=data,
            position_type=position_type,
            price=price,
            balance=self.balance,
        )

        if position_size <= 0:
            return data, None

        order = None
        if create_order:
            order: ExchangeOrder = self.create_market_order(
                trading_pair=self.trading_pair,
                side=(
                    OrderSide.BUY
                    if position_type == PositionType.LONG
                    else OrderSide.SELL
                ),
                price=price,
                amount=position_size,
            )
        amount = order.amount if order else position_size
        open_price = order.price if order else price
        opened_at = order.timestamp if order else timezone.now()
        position = TraderPosition(
            trader=self,
            type=position_type,
            status=PositionStatus.OPENED,
            open_price=open_price,
            amount=amount,
            stop_loss=stop_loss,
            opened_at=timestamp or opened_at,
            take_profit=take_profit,
        )
        return data, position

    def close_position(
        self,
        data: Dict[str, Any],
        position: "TraderPosition",
        price: Decimal,
        create_order: bool = True,
        timestamp: Optional[datetime] = None,
    ) -> "TraderPosition":
        """Закрывает указанную позицию по текущей цене."""
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
        closed_at = order.timestamp if order else timezone.now()
        close_price = order.price if order else price
        position.status = PositionStatus.CLOSED
        position.closed_at = timestamp or closed_at
        position.close_price = close_price
        return data, position

    def update_position(
        self,
        data: Dict[str, Any],
        position: "TraderPosition",
        price: Decimal,
        timestamp: Optional[datetime] = None,
    ) -> "TraderPosition":
        """
        Обновляет позицию трейдера, если она уже открыта.
        Вызывается при получении новой свечи из источника данных.
        """
        # position_type = (
        #     PositionType.LONG
        #     if position.type == PositionType.SHORT
        #     else PositionType.SHORT
        # )

        data, new_stop_loss = self.risk_manager.get_stop_loss(
            data=data,
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

        data, new_take_profit = self.risk_manager.get_take_profit(
            data=data,
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
        return data, position

    # def check_opened_position(
    #     self,
    #     candle: CandleDTO,
    #     create_order: bool = True,
    # ):
    #     self.strategy.handle_candle(candle=candle)
    #     signal = self.strategy.get_signal()
    #     self.save(update_fields=["data"])

    #     if not self.can_open_position(
    #         signal=signal,
    #         price=price,
    #     ):
    #         return

    #     self.data, opened_position = self.open_position(
    #         data=self.data,
    #         signal=signal,
    #         price=price,
    #         create_order=create_order,
    #         timestamp=candle.timestamp,
    #     )
    #     if opened_position:
    #         opened_position.save()

    # def check_opened_position(
    #     self,
    #     candle: Candle,
    #     create_order: bool = True,
    # ) -> None:
    #     if self.signals.filter(
    #         timestamp=candle.timestamp,
    #     ).exists():
    #         logger.warning(
    #             f"Signal for trader {self.pk} at {candle.timestamp} already exists."
    #         )
    #         return

    #     self.data = self.strategy.handle_candle(data=self.data, candle=candle)
    #     self.data, signal = self.strategy.get_signal(self.data)
    #     TraderSignal.objects.create(
    #         trader=self,
    #         timestamp=candle.timestamp,
    #         type=signal,
    #         price=price,
    #     )
    #     self.data = self.update_data(candle=candle)
    #     self.save(update_fields=["data"])

    #     if not self.can_open_position(
    #         signal=signal,
    #         price=price,
    #     ):
    #         return

    #     self.data, opened_position = self.open_position(
    #         data=self.data,
    #         signal=signal,
    #         price=price,
    #         create_order=create_order,
    #     )
