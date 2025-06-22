from django.db import models
from position_managers.domain.positions_managers.base import (
    AbstractPositionManager,
    PositionManagerRegistry,
)
from core.utils.mixins import ActiveManagerMixin, TimeStampedMixin


class PositionManager(ActiveManagerMixin, TimeStampedMixin, models.Model):
    """
    Модель менеджера позиций, которая управляет открытыми позициями трейдера.
    """

    name = models.CharField(max_length=100, unique=True)
    class_name = models.CharField(max_length=100)
    arguments = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Менеджер позиций"
        verbose_name_plural = "Менеджеры позиций"

    def get_class(self) -> AbstractPositionManager:
        return PositionManagerRegistry.get_class(self.class_name)

    def instantiate(self, **kwargs) -> AbstractPositionManager:
        cls = self.get_class()
        return cls(**self.arguments, **kwargs)
