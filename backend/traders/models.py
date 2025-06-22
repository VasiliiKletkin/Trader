from datetime import datetime
from typing import List, Optional

from position_managers.models import PositionManager
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

    # position_manager = models.ForeignKey(
    #     PositionManager,
    #     on_delete=models.CASCADE,
    # )

    initial_balance = models.DecimalField(
        verbose_name="Начальный баланс",
        max_digits=20,
        decimal_places=8,
    )

    data = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Трейдер"
        verbose_name_plural = "Трейдеры"

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
    def exchange_client(self) -> ExchangeClient:
        return self.candle_source.exchange_client

    def open_position(
        self,
        signal: SignalType,
        price: float,
        balance: float = None,
    ) -> Optional["PositionTrader"]:
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

        order: ExchangeOrder = self.create_market_order(
            trading_pair=self.candle_source.trading_pair,
            signal=signal,
            price=price,
            volume=position_size,
        )
        position = PositionTrader(
            trader=self,
            trading_pair=self.candle_source.trading_pair,
            type=PositionType.LONG if signal == SignalType.BUY else PositionType.SHORT,
            status=PositionStatus.OPEN,
            entry_price=price,
            amount=order.amount,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        position.save()
        return position

    def close_position(
        self,
        position: "PositionTrader",
        current_price: float,
    ) -> "PositionTrader":
        """Закрывает указанную позицию по текущей цене."""
        order = self.create_market_order(
            trading_pair=self.candle_source.trading_pair,
            side=(
                OrderSide.SELL if position.type == PositionType.LONG else OrderSide.BUY
            ),
            amount=position.amount,
            price=current_price,
        )
        position.status = PositionStatus.CLOSED
        position.closed_at = timezone.now()
        position.close_price = order.price

        position.save()
        return position

    def trade(self, candle: Candle) -> None:
        price = candle.close
        balance = self.get_balance()

        self.data = self.strategy.handle_candle(candle, self.data)
        signal, self.data = self.strategy.get_signal(self.data)

        positions = self.get_opened_positions()
        opened_positions = list()
        for position in positions:
            if position.should_be_closed(signal, price):
                self.close_position(position, price)
                continue
            opened_positions.append(position)

        if not self.risk_manager.can_trade(
            signal=signal,
            price=price,
            balance=balance,
            opened_positions=opened_positions,
        ):
            return

        self.open_position(
            signal=signal,
            price=price,
            balance=balance,
        )
        self.save()

    def get_profit(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> float:
        """
        Вычисляет реализованную прибыль (PnL) трейдера за указанный период.

        Прибыль рассчитывается как разница между суммарной выручкой от закрытых
        сделок на продажу и суммарными затратами на закрытые сделки на покупку.

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

    def get_opened_positions(self) -> models.QuerySet["PositionTrader"]:
        """
        Возвращает все открытые позиции трейдера.
        """
        return PositionTrader.objects.filter(trader=self, status=PositionStatus.OPEN)

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
            trading_pair=trading_pair.value,
            side=side.value,
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

    def reboot(self):
        candles = Candle.objects.filter(
            candle_source=self.candle_source,
        ).order_by("timestamp")

        self.data = {}
        self.signals.delete()
        new_signals = []
        for candle in candles:
            self.data = self.strategy.handle_candle(
                candle=candle,
                data=self.data,
            )
            signal, self.data = self.strategy.get_signal(self.data)
            if signal in (SignalType.BUY, SignalType.SELL):
                new_signals.append(
                    TraderSignal(
                        trader=self,
                        timestamp=candle.timestamp,
                        type=SignalType(signal),
                        price=candle.close,
                    )
                )
        self.save()
        TraderSignal.objects.bulk_create(new_signals)

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


class PositionTrader(models.Model):
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

    entry_price = models.FloatField()
    close_price = models.FloatField(null=True, blank=True)
    stop_loss = models.FloatField(null=True, blank=True)
    take_profit = models.FloatField(null=True, blank=True)
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    # def unrealized_pnl(self, current_price: float) -> float:
    #     """
    #     Возвращает нереализованную прибыль/убыток (PnL)
    #     """
    #     if self.type == PositionType.LONG:
    #         return (current_price - self.entry_price) * self.amount
    #     else:
    #         return (self.entry_price - current_price) * self.amount

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
