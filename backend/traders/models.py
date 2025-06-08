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
    strategy_data = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Трейдер"
        verbose_name_plural = "Трейдеры"

    def __str__(self):
        return f"{self.candle_source} | {self.strategy}"

    def get_absolute_url(self):
        return reverse("trader_detail", kwargs={"pk": self.pk})

    def handle_candle(
        self,
        candle: Candle,
    ):  # FIXME протестировать старую strategy_data и новую strategy_data если равны то не сохранять
        self.strategy_data = self.strategy.handle_candle(
            candle=candle, data=self.strategy_data
        )
        self.save()

    def get_signal(self) -> SignalType:
        return SignalType(self.strategy.get_signal(data=self.strategy_data))

    def reboot(self):
        candles = Candle.objects.filter(
            candle_source=self.candle_source,
        ).order_by("timestamp")

        self.strategy_data = {}
        for candle in candles:
            self.strategy_data = self.strategy.handle_candle(
                candle=candle, data=self.strategy_data
            )
        self.save()

    @property
    def current_order(self) -> "TraderOrder":
        return (
            self.orders.filter(status=OrderStatus.OPEN).order_by("-timestamp").first()
        )

    @property
    def exchange_client(self) -> ExchangeClient:
        return self.candle_source.exchange_client

    def get_profit(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> float:
        """
        Вычисляет суммарный профит по закрытым сделкам трейдера за указанный период.
        Счёт происходит по принципу FIFO: сначала продаются самые ранние покупки.
        """
        profit = 0.0

        orders: models.QuerySet[TraderOrder] = self.orders.filter(
            status=OrderStatus.CLOSED
        ).order_by("timestamp")

        if start_date:
            orders = orders.filter(timestamp__gte=start_date)
        if end_date:
            orders = orders.filter(timestamp__lte=end_date)

        buys = deque()

        for order in orders:
            if order.side == OrderSide.BUY:
                buys.append({"price": order.price, "amount": order.amount})
            elif order.side == OrderSide.SELL:
                remaining_volume = order.amount
                sell_price = order.price

                while remaining_volume > 0 and buys:
                    buy = buys[0]
                    matched_volume = min(remaining_volume, buy["amount"])

                    profit += (sell_price - buy["price"]) * matched_volume

                    buy["amount"] -= matched_volume
                    remaining_volume -= matched_volume

                    if buy["amount"] <= 0:
                        buys.popleft()

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
        if self.current_order:
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
        related_name="orders",
    )
    exchange_order = models.OneToOneField(
        ExchangeOrder,
        on_delete=models.CASCADE,
        related_name="trader_order",
    )

    class Meta:
        verbose_name = "Ордер трейдера"
        verbose_name_plural = "Ордера трейдера"

    def __str__(self):
        return f"{self.trader} | {self.exchange_order.side} {self.exchange_order.amount} @ {self.exchange_order.price}"


class TraderSignal(models.Model):
    trader = models.ForeignKey(Trader, on_delete=models.CASCADE)
    timestamp = models.DateTimeField()
    type = models.CharField(
        max_length=10,
        choices=SignalType.choices,
        default=SignalType.WAIT,
    )
