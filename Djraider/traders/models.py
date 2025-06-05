from django.db import models
from django.urls import reverse
from strategies.models import Strategy
from exchanges.models import Exchange, Timeframe, TradingPair
from django.db import models


class Trader(models.Model):
    trading_pair = models.ForeignKey(
        TradingPair,
        on_delete=models.CASCADE,
    )
    timeframe = models.CharField(
        max_length=3,
        choices=Timeframe.choices,
        default=Timeframe.ONE_MINUTE,
    )
    exchange = models.ForeignKey(
        Exchange,
        on_delete=models.CASCADE,
    )
    strategy = models.ForeignKey(
        Strategy,
        on_delete=models.CASCADE,
    )

    def get_absolute_url(self):
        return reverse("trader_detail", kwargs={"pk": self.pk})

