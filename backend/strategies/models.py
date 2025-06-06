import inspect
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

    def save(self, *args, **kwargs):
        if not self.arguments:
            cls = self.get_strategy_class()
            sig = inspect.signature(cls.__init__)
            self.arguments = {
                k: v.default
                for k, v in sig.parameters.items()
                if k != "self" and v.default is not inspect.Parameter.empty
            }
        super().save(*args, **kwargs)

    def get_strategy_class(self) -> AbstractStrategy:
        return StrategyRegistry.get_class(self.class_name)

    def instantiate(self, **kwargs) -> AbstractStrategy:
        cls = self.get_strategy_class()
        return cls(**self.arguments, **kwargs)

    def __str__(self) -> str:
        return self.name
