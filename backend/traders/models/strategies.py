from django.db import models

from core.utils.common import get_all_init_args
from core.utils.mixins import ActiveManagerMixin, TimeStampedMixin
from traders.domain.strategies.base import AbstractStrategy, StrategyRegistry


class Strategy(ActiveManagerMixin, TimeStampedMixin, models.Model):
    name = models.CharField(
        max_length=100,
        verbose_name="Название стратегии",
        unique=True,
    )
    class_name = models.CharField(
        max_length=100,
        choices=StrategyRegistry.get_choices,
        verbose_name="Класс стратегии",
    )
    arguments = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Параметры (аргументы)",
    )

    class Meta:
        verbose_name = "Стратегия"
        verbose_name_plural = "Стратегии"

    def __str__(self):
        return f"{self.name} ({self.class_name})"

    def save(self, *args, **kwargs):
        if not self.arguments:
            cls = self.get_class()
            self.arguments = get_all_init_args(cls)
        super().save(*args, **kwargs)

    def get_class(self) -> AbstractStrategy:
        return StrategyRegistry.get_class(self.class_name)

    def get_description(self) -> str:
        cls = self.get_class()
        return (cls.__doc__ or "").strip()

    def instantiate(self, **kwargs) -> AbstractStrategy:
        cls = self.get_class()
        return cls(**self.arguments, **kwargs)  # type: ignore[operator]
