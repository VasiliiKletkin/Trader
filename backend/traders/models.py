from collections import deque
from datetime import datetime
from typing import Optional

from core.utils.mixins import ActiveManagerMixin, TimeStampedMixin
from core.utils.types import OrderSide, SignalType
from django.db import models
from django.urls import reverse
from exchanges.domain.schemas import CandleDTO
from exchanges.models import Candle
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
        return self.strategy.get_signal(data=self.strategy_data)

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

    def get_current_order(self) -> "OrderHistory":
        return self.orders.filter(executed=True).order_by("-timestamp").first()

    def get_profit(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> float:
        """
        Вычисляет суммарный профит по закрытым сделкам трейдера за указанный период.
        """
        profit = 0.0

        orders: models.QuerySet["OrderHistory"] = self.orders
        orders = orders.filter(executed=True).order_by("timestamp")
        if start_date:
            orders = orders.filter(timestamp__gte=start_date)
        if end_date:
            orders = orders.filter(timestamp__lte=end_date)

        if not orders:
            return profit

        buys = deque()

        for order in orders:
            if order.type == OrderSide.BUY:
                buys.append({"price": order.price, "volume": order.volume})
            elif order.type == OrderSide.SELL:
                sell_volume = order.volume
                sell_price = order.price

                while sell_volume > 0 and buys:
                    buy = buys[0]
                    matched_volume = min(buy["volume"], sell_volume)

                    profit += (sell_price - buy["price"]) * matched_volume

                    buy["volume"] -= matched_volume
                    sell_volume -= matched_volume

                    if buy["volume"] == 0:
                        buys.popleft()

        return profit

    def create_order(
        self,
        type: str,
        price: float,
        volume: float,
    ) -> "OrderHistory":
        """
        Создаёт и сохраняет ордер в истории ордеров трейдера.

        Args:
            side: Тип ордера, должен быть 'buy' или 'sell'.
            price: Цена ордера.
            volume: Объём ордера.
        Returns:
            Созданный объект OrderHistory.
        """

        order = OrderHistory.objects.create(
            trader=self,
            type=type,
            price=price,
            volume=volume,
            executed=executed,
            timestamp=timestamp,
        )
        return order


class OrderHistory(models.Model):
    trader = models.ForeignKey(Trader, on_delete=models.CASCADE, related_name="orders")

    executed = models.BooleanField(default=False)
    timestamp = models.DateTimeField()
    type = models.CharField(max_length=4, choices=OrderSide.choices)
    price = models.FloatField()
    volume = models.FloatField()

    class Meta:
        verbose_name = "История ордера"
        verbose_name_plural = "История ордеров"

    def __str__(self):
        return f"{self.trader} | {self.type.upper()} @ {self.price}"


class TraderHistory(models.Model):
    trader = models.ForeignKey(Trader, on_delete=models.CASCADE)
