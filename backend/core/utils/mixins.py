from django.db import models


class ActiveManager(models.Manager):
    def get_queryset(self) -> models.QuerySet:
        return super().get_queryset().filter(is_active=True)


class ActiveManagerMixin(models.Model):
    is_active = models.BooleanField(
        default=False,
        verbose_name="Активен",
    )
    objects = models.Manager()
    active_objects = ActiveManager()

    class Meta:
        abstract = True


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
        return self.created_at.strftime("%d.%m.%Y %H:%M:%S")

    def get_updated_at_display(self) -> str:
        return self.updated_at.strftime("%d.%m.%Y %H:%M:%S")
