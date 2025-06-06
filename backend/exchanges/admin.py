from django.contrib import admin
from dateutil.relativedelta import relativedelta
from django.db.models import QuerySet
from django.utils import timezone

from .models import Exchange, TradingPair, CandleSource, Candle


@admin.register(Exchange)
class ExchangeAdmin(admin.ModelAdmin):
    pass


@admin.register(TradingPair)
class TradingPairAdmin(admin.ModelAdmin):
    pass


@admin.register(Candle)
class CandleAdmin(admin.ModelAdmin):
    pass


@admin.register(CandleSource)
class CandleSourceAdmin(admin.ModelAdmin):
    actions = [
        "save_candles_one_year",
    ]

    @admin.action(description="Сохранить свечи за один год")
    def save_candles_one_year(self, request, queryset: QuerySet[CandleSource]):
        since = timezone.now() - relativedelta(years=1)
        total_saved = 0

        for source in queryset:
            saved_candles = source.save_candles(since=since, limit=300)
            total_saved += len(saved_candles)

        self.message_user(
            request,
            f"✅ Сохранено {total_saved} свечей для {queryset.count()} источников.",
            level="info",
        )
