from django.contrib import admin
from exchanges.models import Candle, Exchange, TradingPair


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


@admin.register(Candle)
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
        "exchange",
        "timeframe",
        "trading_pair",
    ]
    date_hierarchy = "timestamp"
    ordering = [
        "-timestamp",
    ]


@admin.register(TradingPair)
class TradingPairAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "symbol",
        "created_at",
        "updated_at",
    ]
    search_fields = [
        "name",
        "value",
    ]
    ordering = [
        "-created_at",
    ]
