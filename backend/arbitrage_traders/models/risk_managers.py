from django.db import models

from arbitrage_traders.domain.risk_managers import (
    AbstractArbitrageRiskManager,
    ArbitrageRiskManagerRegistry,
)
from core.utils.common import get_all_init_args
from core.utils.mixins import ActiveManagerMixin, TimeStampedMixin


class ArbitrageRiskManager(ActiveManagerMixin, TimeStampedMixin, models.Model):
    name = models.CharField(
        max_length=100,
        verbose_name="Название арбитражного риск-менеджера",
        unique=True,
    )
    class_name = models.CharField(
        max_length=100,
        choices=ArbitrageRiskManagerRegistry.get_choices,
        verbose_name="Класс арбитражного риск-менеджера",
    )
    arguments = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Параметры (аргументы)",
    )

    class Meta:
        verbose_name = "Арбитражный риск-менеджер"
        verbose_name_plural = "Арбитражные риск-менеджеры"

    def __str__(self):
        return f"{self.name} ({self.class_name})"

    def save(self, *args, **kwargs):
        if not self.arguments:
            cls = self.get_class()
            self.arguments = get_all_init_args(cls)
        super().save(*args, **kwargs)

    def get_class(self) -> type[AbstractArbitrageRiskManager]:
        return ArbitrageRiskManagerRegistry.get_class(self.class_name)

    def instantiate(self, **kwargs) -> AbstractArbitrageRiskManager:
        cls = self.get_class()
        return cls(**self.arguments, **kwargs)

    def get_description(self) -> str:
        cls = self.get_class()
        return (cls.__doc__ or "").strip()
