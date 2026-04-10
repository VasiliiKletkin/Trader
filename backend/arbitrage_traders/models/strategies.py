from django.db import models

from arbitrage_traders.domain.strategies import (
    AbstractArbitrageStrategy,
    ArbitrageStrategyRegistry,
)
from core.utils.common import get_all_init_args
from core.utils.models import ActiveManagerMixin, TimeStampedMixin


class ArbitrageStrategy(ActiveManagerMixin, TimeStampedMixin, models.Model):
    name = models.CharField(
        max_length=100,
        verbose_name="Название арбитражной стратегии",
        unique=True,
    )
    class_name = models.CharField(
        max_length=100,
        choices=ArbitrageStrategyRegistry.get_choices,
        verbose_name="Класс арбитражной стратегии",
    )
    arguments = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Параметры (аргументы)",
    )

    class Meta:
        verbose_name = "Арбитражная стратегия"
        verbose_name_plural = "Арбитражные стратегии"

    def __str__(self):
        return f"{self.name} ({self.class_name})"

    def save(self, *args, **kwargs):
        if not self.arguments:
            cls = self.get_class()
            self.arguments = get_all_init_args(cls)
        super().save(*args, **kwargs)

    def get_class(self) -> type[AbstractArbitrageStrategy]:
        return ArbitrageStrategyRegistry.get_class(self.class_name)

    def get_description(self) -> str:
        cls = self.get_class()
        return (cls.__doc__ or "").strip()

    def instantiate(self, **kwargs) -> AbstractArbitrageStrategy:
        cls = self.get_class()
        return cls(**self.arguments, **kwargs)
