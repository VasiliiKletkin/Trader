from django.db import models
from django.utils import timezone

from core.utils.common import dt_str


class ActiveManager(models.Manager):
    def get_queryset(self) -> models.QuerySet:
        return super().get_queryset().filter(is_active=True)


class ActiveManagerMixin(models.Model):
    is_active = models.BooleanField(
        default=True,
        verbose_name="Активен",
    )
    objects = models.Manager()
    active_objects = ActiveManager()

    class Meta:
        abstract = True

    @property
    def is_ready(self) -> bool:
        return self.is_active


class TimeStampedMixin(models.Model):
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Время создания",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Время обновления",
    )

    class Meta:
        abstract = True

    def get_created_at_display(self) -> str:
        local_time = timezone.localtime(self.created_at)
        return dt_str(local_time)

    def get_updated_at_display(self) -> str:
        local_time = timezone.localtime(self.updated_at)
        return dt_str(local_time)
