from django.contrib import admin, messages
from traders.tasks import reboot_trader
from traders.models import Trader, TraderOrder, TraderSignal, TraderPosition
from django.db import models


@admin.register(Trader)
class TraderAdmin(admin.ModelAdmin):
    actions = ["reboot_trader"]

    @admin.action(description="Перезагрузить трейдер")
    def reboot_trader(self, request, queryset: models.QuerySet[Trader]):
        for trader in queryset:
            reboot_trader.delay(trader_id=trader.pk)
        self.message_user(
            request,
            f"{queryset.count()} трейдер(ов) перезагружается.",
            level=messages.SUCCESS,
        )


@admin.register(TraderPosition)
class TraderPositionAdmin(admin.ModelAdmin):
    pass


@admin.register(TraderOrder)
class TraderOrderAdmin(admin.ModelAdmin):
    pass


@admin.register(TraderSignal)
class TraderSignalrAdmin(admin.ModelAdmin):
    pass
