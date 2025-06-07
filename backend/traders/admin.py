from django.contrib import admin
from django.db.models import QuerySet
from .models import OrderHistory, Trader


from django.contrib import admin, messages
from .models import Trader
from exchanges.models import Candle


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


@admin.register(OrderHistory)
class OrderHistoryAdmin(admin.ModelAdmin):
    pass
