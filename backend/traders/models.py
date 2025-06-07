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
    strategy_data = models.JSONField(default=dict, blank=True)

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
