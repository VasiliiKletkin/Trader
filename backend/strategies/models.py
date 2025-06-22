import inspect
from typing import Tuple
from core.utils.types import SignalType
from exchanges.domain.schemas import CandleDTO
from exchanges.models import Candle
from core.utils.mixins import ActiveManagerMixin, TimeStampedMixin
from django.db import models

from .domain.strategies.base import AbstractStrategy, StrategyRegistry


class Strategy(ActiveManagerMixin, TimeStampedMixin, models.Model):
    name = models.CharField(max_length=100)
    class_name = models.CharField(
        max_length=100,
        choices=StrategyRegistry.get_choices,
    )

    arguments = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Стратегия"
        verbose_name_plural = "Стратегии"

    def __str__(self):
        return f"{self.name} ({self.class_name})"

    def save(self, *args, **kwargs):
        if not self.arguments:
            cls = self.get_class()
            sig = inspect.signature(cls.__init__)
            self.arguments = {
                k: v.default
                for k, v in sig.parameters.items()
                if k != "self" and v.default is not inspect.Parameter.empty
            }
        super().save(*args, **kwargs)

    def get_class(self) -> AbstractStrategy:
        return StrategyRegistry.get_class(self.class_name)

    def instantiate(self, **kwargs) -> AbstractStrategy:
        cls = self.get_class()
        return cls(**self.arguments, **kwargs)

    def handle_candle(self, candle: Candle, data: dict) -> dict:
        strategy = self.instantiate()
        strategy.load_data(data)

        candle_dto = CandleDTO(
            dt_unix=candle.dt_unix,
            open=candle.open,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            volume=candle.volume,
        )
        strategy.handle_candle(candle_dto)

        return strategy.dump_data()

    def get_signal(self, data: dict) -> Tuple[SignalType, dict]:
        strategy = self.instantiate()
        strategy.load_data(data)

        signal = strategy.get_signal()
        new_data = strategy.dump_data()

        return SignalType(signal), new_data
