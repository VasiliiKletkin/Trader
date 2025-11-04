from django.db import models
from core.utils.mixins import ActiveManagerMixin


class TelegramBot(ActiveManagerMixin, models.Model):
    name = models.CharField(max_length=255)
    token = models.CharField(max_length=512)

    def __str__(self):
        return self.name


class TelegramChat(ActiveManagerMixin, models.Model):
    bot = models.ForeignKey(TelegramBot, on_delete=models.CASCADE)
    chat_id = models.CharField(max_length=255)
    name = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.name} ({self.chat_id})"
