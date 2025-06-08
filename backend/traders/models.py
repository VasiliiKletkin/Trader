from collections import deque
from datetime import datetime
from typing import Optional

from traders.errors import CreationOrderError
from core.utils.mixins import ActiveManagerMixin, TimeStampedMixin
from core.utils.types import OrderSide, OrderType, SignalType, OrderStatus, TradingPair
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
    data = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Трейдер"
        verbose_name_plural = "Трейдеры"

    def __str__(self):
        return f"{self.candle_source} | {self.strategy}"

    def get_absolute_url(self):
        return reverse("trader_detail", kwargs={"pk": self.pk})

    def handle_candle(self, candle: Candle, data: Optional[dict] = None) -> None:
        new_data = self.strategy.handle_candle(candle, data or self.data)
        if new_data != self.data:
            self.data = new_data
            self.save()

    def get_signal(self, data: Optional[dict] = None) -> SignalType:
        signal, new_data = self.strategy.get_signal(data or self.data)
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

    @property
    def opened_order(self) -> ExchangeOrder:
        return (
            self.orders.filter(status=OrderStatus.OPEN).order_by("-timestamp").first()
        )

    @property
    def orders(self) -> models.QuerySet[ExchangeOrder]:
        return ExchangeOrder.objects.filter(
            id__in=TraderOrder.objects.filter(trader=self).values_list(
                "order_id", flat=True
            )
        )

    @property
    def signals(self) -> models.QuerySet["TraderSignal"]:
        return TraderSignal.objects.filter(trader=self)

    @property
    def exchange_client(self) -> ExchangeClient:
        return self.candle_source.exchange_client

    def get_profit(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> float:
        """
        Вычисляет суммарный профит по закрытым сделкам трейдера за указанный период
        как разницу между выручкой от продаж и затратами на покупки.
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

    def create_market_order(
        self,
        trading_pair: TradingPair,
        side: OrderSide,
        amount: float,
        price: Optional[float] = None,
        params: Optional[dict] = None,
    ) -> "TraderOrder":
        """
        Создаёт и сохраняет ордер в истории ордеров трейдера.

        Args:
            side: Тип ордера, должен быть 'buy' или 'sell'.
            price: Цена ордера.
            volume: Объём ордера.
        Returns:
            Созданный объект OrderHistory.
        """
        if self.opened_order:
            raise CreationOrderError(
                "Нельзя создать новый ордер, если есть незавершенный ордер."
            )

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


# class TraderData(models.Model):
#     trader = models.OneToOneField(
#         Trader,
#         on_delete=models.CASCADE,
#     )
#     data = models.JSONField(default=dict, blank=True)
