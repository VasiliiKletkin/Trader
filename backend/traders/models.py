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

    class Meta:
        verbose_name = "Трейдер"
        verbose_name_plural = "Трейдеры"

    def get_absolute_url(self):
        return reverse("trader_detail", kwargs={"pk": self.pk})
