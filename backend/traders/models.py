from django.db import models
from django.urls import reverse
from exchanges.domain.schemas import Candle
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
    strategy_data = models.JSONField(default=dict)

    class Meta:
        verbose_name = "Трейдер"
        verbose_name_plural = "Трейдеры"

    def get_absolute_url(self):
        return reverse("trader_detail", kwargs={"pk": self.pk})

    def handle_candle(self, candle_obj: CandleModel):
        strategy = self.strategy.instantiate()
        strategy.load_data(self.strategy_data)
        candle = Candle(
            dt_unix=candle_obj.timestamp_unix(),
            open=candle_obj.open,
            high=candle_obj.high,
            low=candle_obj.low,
            close=candle_obj.close,
            volume=candle_obj.volume,
        )
        strategy.handle_candle(candle)
        self.strategy_data = strategy.dump_data()
        self.save()

    def get_signal(self):
        strategy = self.strategy.instantiate()
        strategy.load_data(self.strategy_data)
        return strategy.get_signal()


class TraderHistory(models.Model):
    trader = models.ForeignKey(Trader, on_delete=models.CASCADE)
