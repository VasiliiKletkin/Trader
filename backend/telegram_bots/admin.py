from django.contrib import admin

from .models import TelegramBot, TelegramChat


@admin.register(TelegramBot)
class TelegramBotAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(TelegramChat)
class TelegramChatAdmin(admin.ModelAdmin):
    list_display = ("name", "chat_id", "bot", "is_active")
    list_filter = ("bot", "is_active")
    search_fields = ("name", "chat_id")
    autocomplete_fields = ("bot",)
