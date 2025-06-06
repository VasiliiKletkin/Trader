from django.db import models


class ActiveManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)


class ActiveManagerMixin(models.Model):
    is_active = models.BooleanField(default=False)
    objects = models.Manager()
    active_objects = ActiveManager()

    class Meta:
        abstract = True
