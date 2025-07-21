from typing import Any, Dict, Tuple

from core.utils.common import get_all_init_args
from core.utils.mixins import ActiveManagerMixin, TimeStampedMixin
from core.utils.types import SignalType
from strategies.domain.schemas import SignalType
from django.db import models
from exchanges.domain.schemas import Candle as DomainCandle
from exchanges.models import Candle

from .domain.base import AbstractStrategy, StrategyRegistry


class Strategy(ActiveManagerMixin, TimeStampedMixin, models.Model):
    name = models.CharField(max_length=100, verbose_name="Название стратегии")
    class_name = models.CharField(
        max_length=100,
        choices=StrategyRegistry.get_choices,
        verbose_name="Класс стратегии",
    )
    arguments = models.JSONField(
        default=dict, blank=True, verbose_name="Параметры (аргументы)"
    )

    class Meta:
        verbose_name = "Стратегия"
        verbose_name_plural = "Стратегии"

    def __str__(self):
        return f"{self.name} ({self.class_name}) {self.arguments}"

    def save(self, *args, **kwargs):
        if not self.arguments:
            cls = self.get_class()
            self.arguments = get_all_init_args(cls)
        super().save(*args, **kwargs)

    def get_class(self) -> AbstractStrategy:
        return StrategyRegistry.get_class(self.class_name)

    def get_description(self) -> str:
        """
        Возвращает docstring (описание) выбранного risk-менеджера.
        """
        cls = self.get_class()
        return (cls.__doc__ or "").strip()

    def instantiate(self, **kwargs) -> AbstractStrategy:
        cls = self.get_class()
        return cls(**self.arguments, **kwargs)

    def handle_candle(
        self,
        data: Dict[str, Any],
        candle: Candle,
    ) -> Dict[str, Any]:
        strategy = self.instantiate()
        strategy.load_data(data)

        candle_dto = DomainCandle(
            dt_unix=candle.dt_unix,
            open=candle.open,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            volume=candle.volume,
        )
        strategy.handle_candle(candle_dto)
        return {**data, **strategy.dump_data()}

    def get_signal(self, data: Dict[str, Any]) -> Tuple[Dict[str, Any], SignalType]:
        strategy = self.instantiate()
        strategy.load_data(data)
        signal = strategy.get_signal()
        return {**data, **strategy.dump_data()}, SignalType(signal)
