from django.contrib import admin, messages
from traders.models import Trader, TraderOrder
from django.db import models


@admin.register(Trader)
class TraderAdmin(admin.ModelAdmin):
    actions = ["reboot_trader"]

    @admin.action(description="Перезагрузить трейдер")
    def reboot_trader(self, request, queryset: models.QuerySet[Trader]):
        for trader in queryset:
            trader.reboot()
        self.message_user(
            request,
            f"{queryset.count()} трейдер(ов) успешно перезагружено.",
            level=messages.SUCCESS,
        )


@admin.register(TraderOrder)
class TraderOrderAdmin(admin.ModelAdmin):
    pass
