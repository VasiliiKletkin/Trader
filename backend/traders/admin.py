from django.contrib import admin
from django.db.models import QuerySet
from .models import Trader


from django.contrib import admin, messages
from .models import Trader
from exchanges.models import Candle


@admin.register(Trader)
class TraderAdmin(admin.ModelAdmin):
    actions = ["reprocess_all_candles"]

    @admin.action(description="Перепроцессить все результаты для выбранных трейдеров")
    def reprocess_all_candles(self, request, queryset: QuerySet[Trader]):
        for trader in queryset:
            trader.reprocess_all_candles()
        self.message_user(
            request,
            f"{queryset.count()} трейдер(ов) успешно перепроцессены.",
            level=messages.SUCCESS,
        )
