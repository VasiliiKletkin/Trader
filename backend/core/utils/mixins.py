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


class BaseErrorMixin(models.Model):
    message = models.TextField(
        verbose_name="Сообщение об ошибке",
    )
    type = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Тип ошибки",
    )
    traceback = models.TextField(
        blank=True,
        default="",
        verbose_name="Traceback",
    )

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return f"{self.type} | {self.message[:100]}"


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
