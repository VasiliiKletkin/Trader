from django.db import models

from core.utils.common import get_all_init_args
from core.utils.mixins import ActiveManagerMixin, TimeStampedMixin
from traders.domain.risk_managers.base import AbstractRiskManager, RiskManagerRegistry


class RiskManager(ActiveManagerMixin, TimeStampedMixin, models.Model):
    name = models.CharField(
        max_length=100,
        verbose_name="Название риск-менеджера",
        unique=True,
    )
    class_name = models.CharField(
        max_length=100,
        choices=RiskManagerRegistry.get_choices,
        verbose_name="Класс риск-менеджера",
    )
    arguments = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Параметры (аргументы)",
    )

    class Meta:
        verbose_name = "Риск-менеджер"
        verbose_name_plural = "Риск-менеджеры"

    def __str__(self):
        return f"{self.name} ({self.class_name})"

    def save(self, *args, **kwargs):
        if not self.arguments:
            cls = self.get_class()
            self.arguments = get_all_init_args(cls)
        super().save(*args, **kwargs)

    def get_class(self) -> AbstractRiskManager:
        return RiskManagerRegistry.get_class(self.class_name)

    def instantiate(self, **kwargs) -> AbstractRiskManager:
        cls = self.get_class()
        return cls(**self.arguments, **kwargs)  # type: ignore[operator]

    def get_description(self) -> str:
        cls = self.get_class()
        return (cls.__doc__ or "").strip()
