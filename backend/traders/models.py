from django.db import models
from django.urls import reverse
from exchanges.domain.schemas import Candle
from core.utils.mixins import TimeStampedMixin, ActiveManagerMixin
from exchanges.models import CandleSource, Candle as CandleModel
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


class TraderHistory(models.Model):
    trader = models.ForeignKey(Trader, on_delete=models.CASCADE)
