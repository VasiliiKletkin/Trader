from admin_auto_filters.filters import AutocompleteFilter
from django.contrib import admin

from exchanges.models import (
    Exchange,
    ExchangeCandle,
    ExchangeTradingPair,
    TradingPair,
)


class ExchangeFilter(AutocompleteFilter):
    title = "Exchange"
    field_name = "exchange"


class TradingPairFilter(AutocompleteFilter):
    title = "Trading Pair"
    field_name = "trading_pair"


@admin.register(Exchange)
class ExchangeAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "class_name",
        "is_active",
        "created_at",
        "updated_at",
    ]
    ordering = [
        "-created_at",
    ]
    search_fields = [
        "name",
    ]
    list_filter = [
        "is_active",
        "class_name",
    ]


@admin.register(ExchangeCandle)
class CandleAdmin(admin.ModelAdmin):
    list_display = [
        "exchange",
        "timeframe",
        "trading_pair",
        "timestamp",
        "high",
        "low",
        "open",
        "close",
        "volume",
    ]
    list_filter = [
        ExchangeFilter,
        TradingPairFilter,
        "timeframe",
    ]
    date_hierarchy = "timestamp"
    ordering = [
        "-timestamp",
    ]


class ExchangeTradingPairInline(admin.TabularInline):
    model = ExchangeTradingPair
    extra = 1


@admin.register(TradingPair)
class TradingPairAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "type",
        "created_at",
        "updated_at",
    ]
    search_fields = [
        "name",
        "symbol",
    ]
    list_filter = [
        "type",
    ]
    ordering = [
        "-created_at",
    ]

    inlines = [
        ExchangeTradingPairInline,
    ]
