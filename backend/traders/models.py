from collections import deque
from datetime import datetime
from typing import List, Optional, Tuple

from core.utils.mixins import ActiveManagerMixin, TimeStampedMixin
from django.db import models
from django.urls import reverse
from exchanges.domain.schemas import Candle
from exchanges.models import Candle as CandleModel
from exchanges.models import CandleSource
from strategies.models import Strategy


class OrderType(models.TextChoices):
    BUY = "buy", "Buy"
    SELL = "sell", "Sell"


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

    def handle_candle(self, candle_model: CandleModel):
        strategy = self.strategy.instantiate()
        strategy.load_data(self.strategy_data)
        candle = Candle(
            dt_unix=candle_model.timestamp_unix(),
            open=candle_model.open,
            high=candle_model.high,
            low=candle_model.low,
            close=candle_model.close,
            volume=candle_model.volume,
        )
        strategy.handle_candle(candle)
        self.strategy_data = strategy.dump_data()
        self.save()

    def get_signal(self):
        strategy = self.strategy.instantiate()
        strategy.load_data(self.strategy_data)
        return strategy.get_signal()

    def reprocess_all_candles(self):
        candles = CandleModel.objects.filter(
            candle_source=self.candle_source,
        ).order_by("timestamp")

        strategy = self.strategy.instantiate()
        strategy.load_data({})

        for candle_model in candles:
            candle = Candle(
                dt_unix=candle_model.timestamp_unix(),
                open=candle_model.open,
                high=candle_model.high,
                low=candle_model.low,
                close=candle_model.close,
                volume=candle_model.volume,
            )
            strategy.handle_candle(candle)

        self.strategy_data = strategy.dump_data()
        self.save()

    def get_profit(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> float:
        """
        Вычисляет суммарный профит по закрытым сделкам трейдера за указанный период.
        """
        orders: models.QuerySet["OrderHistory"] = self.orders.order_by("timestamp")
        profit = 0.0

        if start_date:
            orders = orders.filter(timestamp__gte=start_date)
        if end_date:
            orders = orders.filter(timestamp__lte=end_date)

        if not orders:
            return profit

        buys = deque()

        for order in orders:
            if order.type == OrderType.BUY:
                buys.append({"price": order.price, "volume": order.volume})
            elif order.type == OrderType.SELL:
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


class TraderHistory(models.Model):
    trader = models.ForeignKey(Trader, on_delete=models.CASCADE)


class OrderHistory(models.Model):
    trader = models.ForeignKey(Trader, on_delete=models.CASCADE, related_name="orders")

    executed = models.BooleanField(default=False)
    timestamp = models.DateTimeField()
    type = models.CharField(max_length=4, choices=OrderType.choices)
    price = models.FloatField()
    volume = models.FloatField()

    class Meta:
        verbose_name = "История ордера"
        verbose_name_plural = "История ордеров"

    def __str__(self):
        return f"{self.trader} | {self.type.upper()} @ {self.price}"
