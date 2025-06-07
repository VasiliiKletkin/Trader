from django.contrib import admin
from django.db.models import QuerySet
from .models import Candle, CandleSource, ExchangeClient


@admin.register(ExchangeClient)
class ExchangeClientAdmin(admin.ModelAdmin):
    pass


@admin.register(Candle)
class CandleAdmin(admin.ModelAdmin):
    pass


@admin.register(CandleSource)
class CandleSourceAdmin(admin.ModelAdmin):
    actions = [
        "save_candles_one_thousand",
    ]

    @admin.action(description="Сохранить по 1000 свечей")
    def save_candles_one_thousand(self, request, queryset: QuerySet[CandleSource]):
        total_saved = 0

        for source in queryset:
            saved_candles = source.fetch_candles(limit=1000)
            total_saved += len(saved_candles)

        self.message_user(
            request,
            f"✅ Сохранено {total_saved} свечей для {queryset.count()} источников.",
            level="info",
        )
