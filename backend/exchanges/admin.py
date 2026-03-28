from admin_auto_filters.filters import AutocompleteFilter
from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest

from exchanges.models import (
    Exchange,
    ExchangeCandle,
    ExchangeTradingPair,
    TradingPair,
)
from exchanges.tasks import exchange_sync_trading_pairs


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
        "created_at",
        "updated_at",
        "is_active",
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
    actions = [
        "load_markets",
    ]

    @admin.action(description="Загрузить торговые пары с биржи")
    def load_markets(self, request: HttpRequest, queryset: QuerySet[Exchange]) -> None:
        for exchange in queryset:
            exchange_sync_trading_pairs.delay(exchange.id)
            self.message_user(
                request,
                f"{exchange.name}: задача загрузки торговых пар запущена",
                messages.SUCCESS,
            )


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
    autocomplete_fields = [
        "exchange",
        "trading_pair",
    ]
    ordering = [
        "-timestamp",
    ]
    list_select_related = [
        "exchange",
        "trading_pair",
    ]
    show_full_result_count = False


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
