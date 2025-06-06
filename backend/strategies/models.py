import inspect
from django.db import models

from .domain.base import StrategyRegistry


class Strategy(models.Model):
    is_active = models.BooleanField(default=False)

    name = models.CharField(max_length=100)
    class_name = models.CharField(
        max_length=100,
        choices=StrategyRegistry.get_choices,
        default="RenkoStrategy",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    arguments = models.JSONField()

    class Meta:
        verbose_name = "Стратегия"
        verbose_name_plural = "Стратегии"

    def get_strategy_class(self):
        return StrategyRegistry.get_class(self.class_name)

    def instantiate(self, **kwargs):
        cls = self.get_strategy_class()
        return cls(**self.arguments, **kwargs)

    def __str__(self):
        return self.name
