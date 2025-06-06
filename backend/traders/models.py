from django.db import models
from django.urls import reverse
from exchanges.models import CandleSource
from strategies.models import Strategy


class Trader(models.Model):
    candle_source = models.ForeignKey(
        CandleSource,
        on_delete=models.CASCADE,
    )
    strategy = models.ForeignKey(
        Strategy,
        on_delete=models.CASCADE,
    )

    def get_absolute_url(self):
        return reverse("trader_detail", kwargs={"pk": self.pk})
