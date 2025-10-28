from django.db import models


class TelegramBot(models.Model):
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    token = models.CharField(max_length=512)

    def __str__(self):
        return self.name


class TelegramChat(models.Model):
    bot = models.ForeignKey(TelegramBot, on_delete=models.CASCADE)
    chat_id = models.CharField(max_length=255)
    name = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return f"{self.name} ({self.chat_id})"
