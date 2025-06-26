from datetime import datetime
from typing import Dict, List, Optional
from django.db.models import F, ExpressionWrapper, FloatField, Sum, Q, Case, When

from risk_managers.models import RiskManager
from core.utils.mixins import ActiveManagerMixin, TimeStampedMixin
from core.utils.types import (
    OrderSide,
    PositionStatus,
    PositionType,
    SignalType,
    OrderStatus,
    TradingPair,
)
from django.utils import timezone
from django.db import models
from django.urls import reverse
from exchanges.models import Candle, ExchangeClient, ExchangeOrder
from exchanges.models import CandleSource
from strategies.models import Strategy


class Trader(TimeStampedMixin, ActiveManagerMixin, models.Model):
    candle_source = models.ForeignKey(
        CandleSource,
        on_delete=models.CASCADE,
        related_name="traders",
    )
    strategy = models.ForeignKey(
        Strategy,
        on_delete=models.CASCADE,
    )

    risk_manager = models.ForeignKey(
        RiskManager,
        on_delete=models.CASCADE,
    )

    initial_balance = models.DecimalField(
        verbose_name="Начальный баланс",
        max_digits=20,
        decimal_places=2,
    )

    last_reboot = models.DateTimeField(
        verbose_name="Последний перезапуск",
        null=True,
        blank=True,
    )

    data = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Трейдер"
        verbose_name_plural = "Трейдеры"
        constraints = [
            models.UniqueConstraint(
                fields=["candle_source", "strategy", "risk_manager", "initial_balance"],
                name="unique_trader_constraint",
            )
        ]

    def __str__(self):
        return f"{self.candle_source} | {self.strategy}"

    def get_absolute_url(self):
        return reverse("trader_detail", kwargs={"pk": self.pk})

    @property
    def orders(self) -> models.QuerySet[ExchangeOrder]:
        return ExchangeOrder.objects.filter(traderorder__trader=self)

    @property
    def signals(self) -> models.QuerySet["TraderSignal"]:
        return TraderSignal.objects.filter(trader=self)

    @property
    def positions(self) -> models.QuerySet["TraderPosition"]:
        return TraderPosition.objects.filter(trader=self)

    @property
    def exchange_client(self) -> ExchangeClient:
        return self.candle_source.exchange_client

    def reboot(self):
        create_order = False
        candles = Candle.objects.filter(
            candle_source=self.candle_source,
        ).order_by("timestamp")

        self.data = {}
        self.signals.delete()
        self.positions.delete()

        all_signals: List[TraderSignal] = []
        all_positions: List[TraderPosition] = []

        opened_positions: List[TraderPosition] = []
        self.last_reboot = timezone.now()
        self.save()
        for candle in candles.iterator():
            price = float(candle.close)
            balance = float(self.get_balance())

            self.data = self.strategy.handle_candle(candle, self.data)
            signal, self.data = self.strategy.get_signal(self.data)
            if signal in (SignalType.BUY, SignalType.SELL):
                all_signals.append(
                    TraderSignal(
                        trader=self,
                        timestamp=candle.timestamp,
                        type=SignalType(signal),
                        price=candle.close,
                    )
                )
            for position in opened_positions:
                if position.should_be_closed(signal, price):
                    closed_position = self.close_position(
                        position=position,
                        price=price,
                        create_order=create_order,
                        timestamp=candle.timestamp,
                    )
                    opened_positions.remove(closed_position)

            params = {
                "initial_balance": self.initial_balance,
            }
            if not self.risk_manager.can_trade(
                signal=signal,
                price=price,
                balance=balance,
                opened_positions=opened_positions,
                **params,
            ):
                continue

            opened_position = self.open_position(
                signal=signal,
                price=price,
                balance=balance,
                create_order=create_order,
                timestamp=candle.timestamp,
            )
            opened_positions.append(opened_position)
            all_positions.append(opened_position)

        TraderPosition.objects.bulk_create(all_positions)
        TraderSignal.objects.bulk_create(all_signals)
        self.save()

    def trade(self, candle: Candle) -> None:
        price = float(candle.close)
        balance = float(self.get_balance())
        create_order = self.is_active

        self.data = self.strategy.handle_candle(candle, self.data)
        signal, self.data = self.strategy.get_signal(self.data)
        if signal in {SignalType.BUY, SignalType.SELL}:
            TraderSignal.objects.create(
                trader=self,
                timestamp=candle.timestamp,
                type=SignalType(signal),
                price=candle.close,
            )
        positions = self.get_opened_positions()
        opened_positions = list()
        for position in positions:
            if position.should_be_closed(signal, price):
                closed_position = self.close_position(
                    position=position,
                    price=price,
                    create_order=create_order,
                )
                closed_position.save()
            else:
                opened_positions.append(position)

        params = {
            "initial_balance": self.initial_balance,
        }
        if not self.risk_manager.can_trade(
            signal=signal,
            price=price,
            balance=balance,
            opened_positions=opened_positions,
            **params,
        ):
            return

        opened_position = self.open_position(
            signal=signal,
            price=price,
            balance=balance,
            create_order=create_order,
        )
        opened_position.save()
        self.save()

    def open_position(
        self,
        signal: SignalType,
        price: float,
        balance: float,
        create_order: bool = True,
        timestamp: Optional[datetime] = None,
    ) -> Optional["TraderPosition"]:
        """
        Открывает позицию на основе сигнала и текущей цены.
        """
        stop_loss = self.risk_manager.get_stop_loss(price=price)
        take_profit = self.risk_manager.get_take_profit(price=price)

        position_size = self.risk_manager.calculate_position_size(
            price=price,
            balance=balance,
        )

        if position_size <= 0:
            return

        order = None
        if create_order:
            order: ExchangeOrder = self.create_market_order(
                trading_pair=TradingPair(self.candle_source.trading_pair),
                side=OrderSide.BUY if signal == SignalType.BUY else OrderSide.SELL,
                price=price,
                volume=position_size,
            )
        amount = order.amount if order else position_size
        entry_price = order.price if order else price
        opened_at = order.timestamp if order else timezone.now()
        position = TraderPosition(
            trader=self,
            type=PositionType.LONG if signal == SignalType.BUY else PositionType.SHORT,
            status=PositionStatus.OPEN,
            entry_price=entry_price,
            amount=amount,
            stop_loss=stop_loss,
            opened_at=timestamp or opened_at,
            take_profit=take_profit,
        )
        return position

    def close_position(
        self,
        position: "TraderPosition",
        price: float,
        create_order: bool = True,
        timestamp: Optional[datetime] = None,
    ) -> "TraderPosition":
        """Закрывает указанную позицию по текущей цене."""
        order = None
        if create_order:
            order = self.create_market_order(
                trading_pair=TradingPair(self.candle_source.trading_pair),
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
        return position

    def get_profit(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> float:
        """
        Вычисляет реализованную прибыль (PnL) трейдера за указанный период.

        Прибыль рассчитывается как разница между суммарной выручкой от закрытых
        сделок на продажу и суммарными затратами на закрытые сделки на покупку.
        Эта функция учитывает только ордеры, которые были открыты и закрыты в указанный период.

        Args:
            start_date (Optional[datetime]): Начальная дата периода, если указана.
            end_date (Optional[datetime]): Конечная дата периода, если указана.

        Returns:
            float: Общая реализованная прибыль за указанный период.
                   Значение может быть как положительным, так и отрицательным.
        """
        orders = self.orders.filter(status=OrderStatus.CLOSED)

        if start_date:
            orders = orders.filter(timestamp__gte=start_date)
        if end_date:
            orders = orders.filter(timestamp__lte=end_date)

        buy_total = (
            orders.filter(side=OrderSide.BUY).aggregate(
                total=models.Sum(models.F("price") * models.F("amount"))
            )["total"]
            or 0.0
        )

        sell_total = (
            orders.filter(side=OrderSide.SELL).aggregate(
                total=models.Sum(models.F("price") * models.F("amount"))
            )["total"]
            or 0.0
        )

        profit = sell_total - buy_total
        return round(profit, 2)

    def get_theoretical_profit(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> float:
        """
        Вычисляет реализованную прибыль (PnL) трейдера за указанный период.

        Прибыль рассчитывается как разница между суммарной выручкой от итогов позиций
        на продажу и суммарными затратами на закрытые позиции на покупку.
        Эта функция учитывает только позиции, которые были открыты и закрыты в указанный период.

        Args:
            start_date (Optional[datetime]): Начальная дата периода, если указана.
            end_date (Optional[datetime]): Конечная дата периода, если указана.

        Returns:
            float: Общая реализованная прибыль за указанный период.
            Значение может быть как положительным, так и отрицательным.
        """

        filters = Q(status=PositionStatus.CLOSED)

        if start_date:
            filters &= Q(opened_at__gte=start_date)
        if end_date:
            filters &= Q(closed_at__lte=end_date)

        positions = self.positions.filter(filters)

        profit_expression = Case(
            When(
                type=PositionType.LONG,
                then=ExpressionWrapper(
                    (F("close_price") - F("entry_price")) * F("amount"),
                    output_field=FloatField(),
                ),
            ),
            When(
                type=PositionType.SHORT,
                then=ExpressionWrapper(
                    (F("entry_price") - F("close_price")) * F("amount"),
                    output_field=FloatField(),
                ),
            ),
            default=0.0,
            output_field=FloatField(),
        )

        result = positions.aggregate(total_profit=Sum(profit_expression))
        return result["total_profit"] or 0.0

    def get_balance(self, date: Optional[datetime] = None) -> float:
        """
        Возвращает текущий виртуальный баланс трейдера, исходя из стартового капитала
        и реализованной прибыли за указанный период.

        Баланс = начальный капитал + реализованная прибыль за дату

        Args:
            date (Optional[datetime]): Дата.

        Returns:
            float: Расчётный виртуальный баланс трейдера.
        """
        return round(self.initial_balance or 0.0 + self.get_profit(end_date=date), 2)

    def get_opened_positions(self) -> models.QuerySet["TraderPosition"]:
        """
        Возвращает все открытые позиции трейдера.
        """
        return TraderPosition.objects.filter(trader=self, status=PositionStatus.OPEN)

    def get_closed_positions(self) -> models.QuerySet["TraderPosition"]:
        """
        Возвращает все закрытые позиции трейдера.
        """
        return TraderPosition.objects.filter(trader=self, status=PositionStatus.CLOSED)

    def create_market_order(
        self,
        trading_pair: TradingPair,
        side: OrderSide,
        amount: float,
        price: Optional[float] = None,
        params: Optional[dict] = None,
    ) -> ExchangeOrder:
        """
        Создаёт и сохраняет ордер в истории ордеров трейдера.

        Args:
            side: Тип ордера, должен быть 'buy' или 'sell'.
            price: Цена ордера.
            volume: Объём ордера.
        Returns:
            Созданный объект OrderHistory.
        """
        created_order = self.exchange_client.create_market_order(
            trading_pair=trading_pair,
            side=side,
            amount=amount,
            price=price,
            params=params,
        )

        TraderOrder.objects.create(
            exchange_order=created_order,
            trader=self,
        )
        return created_order

    def handle_candle(self, candle: Candle) -> None:
        new_data = self.strategy.handle_candle(candle, self.data)
        if new_data != self.data:
            self.data = new_data
            self.save()

    def get_signal(self) -> SignalType:
        signal, new_data = self.strategy.get_signal(self.data)
        if new_data != self.data:
            self.data = new_data
            self.save()
        return signal

    def can_trade(
        self,
        signal: SignalType,
        price: float,
        balance: Optional[float],
        opened_positions: Optional[List],
    ) -> bool:
        return self.risk_manager.can_trade(
            signal=signal,
            price=price,
            balance=balance or self.get_balance(),
            opened_positions=opened_positions or self.get_opened_positions(),
        )


class TraderOrder(TimeStampedMixin, models.Model):
    trader = models.ForeignKey(
        Trader,
        on_delete=models.CASCADE,
    )
    order = models.OneToOneField(
        ExchangeOrder,
        on_delete=models.CASCADE,
    )

    class Meta:
        verbose_name = "Ордер трейдера"
        verbose_name_plural = "Ордера трейдера"

    def __str__(self):
        return f"{self.trader} | {self.order.side} {self.order.amount} @ {self.order.price}"


class TraderSignal(models.Model):
    trader = models.ForeignKey(
        Trader,
        on_delete=models.CASCADE,
    )
    timestamp = models.DateTimeField()
    type = models.CharField(
        max_length=10,
        choices=SignalType.choices,
    )
    price = models.DecimalField(
        max_digits=20,
        decimal_places=8,
    )

    class Meta:
        verbose_name = "Сигнал трейдера"
        verbose_name_plural = "Сигналы трейдера"


class TraderPosition(models.Model):
    trader = models.ForeignKey(
        Trader,
        on_delete=models.CASCADE,
    )
    type = models.CharField(
        max_length=10,
        choices=PositionType.choices,
    )
    status = models.CharField(
        max_length=10,
        choices=PositionStatus.choices,
        default=PositionStatus.OPEN,
    )
    amount = models.FloatField()

    entry_price = models.FloatField(null=True, blank=True)
    close_price = models.FloatField(null=True, blank=True)
    stop_loss = models.FloatField(null=True, blank=True)
    take_profit = models.FloatField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Позиция трейдера"
        verbose_name_plural = "Позиции трейдера"

    def __str__(self):
        return f"{self.get_status_display()} | {self.get_type_display()} | pnl:{self.realized_pnl()}"

    def realized_pnl(self) -> Optional[float]:
        """
        Возвращает реализованный PnL (если позиция закрыта).
        """
        if self.status != PositionStatus.CLOSED or self.close_price is None:
            return 0

        if self.type == PositionType.LONG:
            return (self.close_price - self.entry_price) * self.amount
        if self.type == PositionType.SHORT:
            return (self.entry_price - self.close_price) * self.amount

    def unrealized_pnl(self, current_price: float) -> float:
        """
        Возвращает текущую нереализованную прибыль/убыток (PnL).
        """
        if self.status != PositionStatus.OPEN:
            return 0.0

        if self.type == PositionType.LONG:
            return (current_price - self.entry_price) * self.amount
        else:
            return (self.entry_price - current_price) * self.amount

    def should_be_closed(self, signal: SignalType, current_price: float) -> bool:
        """
        Определяет, нужно ли закрывать позицию по текущему сигналу и цене.

        Логика:
        - Если пришёл противоположный сигнал (например, позиция LONG, сигнал SELL) — закрываем.
        - Если цена достигла стоп-лосса или тейк-профита — закрываем.
        - Иначе — оставляем открытую.

        :param signal: Текущий торговый сигнал
        :param current_price: Текущая цена инструмента
        :return: True, если позицию нужно закрыть, иначе False
        """
        if self.status != PositionStatus.OPEN:
            return False  # Позиция уже закрыта

        # Закрытие при противоположном сигнале
        if self.type == PositionType.LONG and signal == SignalType.SELL:
            return True
        if self.type == PositionType.SHORT and signal == SignalType.BUY:
            return True

        # Закрытие при достижении стоп-лосса или тейк-профита
        if self.stop_loss is not None:
            if self.type == PositionType.LONG and current_price <= self.stop_loss:
                return True
            if self.type == PositionType.SHORT and current_price >= self.stop_loss:
                return True

        if self.take_profit is not None:
            if self.type == PositionType.LONG and current_price >= self.take_profit:
                return True
            if self.type == PositionType.SHORT and current_price <= self.take_profit:
                return True

        return False
