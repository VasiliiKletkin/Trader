from django.db import models

from core.utils.mixins import ActiveManagerMixin


class TelegramBot(ActiveManagerMixin, models.Model):
    name = models.CharField(max_length=255, verbose_name="Название")
    token = models.CharField(max_length=512, verbose_name="Токен")

    class Meta:
        verbose_name = "Telegram бот"
        verbose_name_plural = "Telegram боты"

    def __str__(self):
        return self.name


class TelegramChat(ActiveManagerMixin, models.Model):
    bot = models.ForeignKey(TelegramBot, on_delete=models.CASCADE, verbose_name="Бот")
    chat_id = models.CharField(max_length=255, verbose_name="ID чата")
    name = models.CharField(max_length=255, verbose_name="Название")

    class Meta:
        verbose_name = "Telegram чат"
        verbose_name_plural = "Telegram чаты"

    def __str__(self):
        return f"{self.name} ({self.chat_id})"
