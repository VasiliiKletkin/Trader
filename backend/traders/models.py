from django.db import models
from django.urls import reverse
from core.utils.mixins import TimeStampedMixin
from exchanges.models import CandleSource, Candle as CandleModel
from strategies.models import Strategy


class Trader(TimeStampedMixin, models.Model):
    candle_source = models.ForeignKey(
        CandleSource,
        on_delete=models.CASCADE,
    )
    strategy = models.ForeignKey(
        Strategy,
        on_delete=models.CASCADE,
    )
    strategy_state = models.JSONField(default=dict)

    class Meta:
        verbose_name = "Трейдер"
        verbose_name_plural = "Трейдеры"

    def get_absolute_url(self):
        return reverse("trader_detail", kwargs={"pk": self.pk})

    def handle_candle(self, candle: CandleModel):
        pass



class TraderHistory(models.Model):
    trader = models.ForeignKey(Trader, on_delete=models.CASCADE)
