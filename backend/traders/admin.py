from django.contrib import admin, messages
from django.db.models import QuerySet
from traders.models import Trader, TraderOrder


@admin.register(Trader)
class TraderAdmin(admin.ModelAdmin):
    actions = ["reboot_trader"]

    @admin.action(description="Перезагрузить трейдер")
    def reboot_trader(self, request, queryset: QuerySet[Trader]):
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
