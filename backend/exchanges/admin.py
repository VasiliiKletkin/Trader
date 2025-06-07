from django.contrib import admin
from django.db.models import QuerySet
from .models import Candle, CandleSource, ExchangeClient, ExchangeOrder


@admin.register(ExchangeClient)
class ExchangeClientAdmin(admin.ModelAdmin):
    actions = [
        "fetch_orders_last_thousand",
    ]

    @admin.action(description="Сохранить последние 1000 ордеров")
    def fetch_orders_last_thousand(self, request, queryset: QuerySet[ExchangeClient]):
        total_saved = 0

        for client in queryset:
            orders = client.fetch_orders(limit=1000)
            total_saved += len(orders)

        self.message_user(
            request,
            f"✅ Сохранено {total_saved} ордеров для {queryset.count()} клиентов.",
            level="info",
        )


@admin.register(ExchangeOrder)
class ExchangeOrderAdmin(admin.ModelAdmin):
    pass


@admin.register(Candle)
class CandleAdmin(admin.ModelAdmin):
    pass


@admin.register(CandleSource)
class CandleSourceAdmin(admin.ModelAdmin):
    actions = [
        "fetch_candles_last_thousand",
    ]

    @admin.action(description="Сохранить по 1000 свечей")
    def fetch_candles_last_thousand(self, request, queryset: QuerySet[CandleSource]):
        total_saved = 0

        for source in queryset:
            saved_candles = source.fetch_candles(limit=1000)
            total_saved += len(saved_candles)

        self.message_user(
            request,
            f"✅ Сохранено {total_saved} свечей для {queryset.count()} источников.",
            level="info",
        )
