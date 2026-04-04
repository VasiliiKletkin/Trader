from django.contrib import admin

from .models import TelegramBot, TelegramChat
from .tasks import send_notification


@admin.register(TelegramBot)
class TelegramBotAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
    actions = ("test_notification",)

    @admin.action(description="Отправить тестовое уведомление")
    def test_notification(self, request, queryset):
        send_notification.delay(message="Тестовое уведомление")
        self.message_user(request, "Тестовое уведомление отправлено")


@admin.register(TelegramChat)
class TelegramChatAdmin(admin.ModelAdmin):
    list_display = ("name", "chat_id", "bot", "is_active")
    list_filter = ("is_active", "bot")
    search_fields = ("name", "chat_id")
    autocomplete_fields = ("bot",)
    list_select_related = ("bot",)
