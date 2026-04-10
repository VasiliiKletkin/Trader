from admin_auto_filters.filters import AutocompleteFilter
from celery import group
from django import forms
from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest

from exchanges.models import (
    Exchange,
    ExchangeCandle,
    ExchangeTradingPair,
    TradingPair,
)
from exchanges.schemas import MarketType
from exchanges.tasks import exchange_sync_trading_pairs


class ExchangeFilter(AutocompleteFilter):
    title = "Exchange"
    field_name = "exchange"


class TradingPairFilter(AutocompleteFilter):
    title = "Trading Pair"
    field_name = "trading_pair"


class ExchangeAdminForm(forms.ModelForm):
    market_types = forms.MultipleChoiceField(
        choices=MarketType.choices,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Типы рынков",
    )

    class Meta:
        model = Exchange
        fields = [
            "name",
            "class_name",
            "max_candles_per_request",
            "timeout",
            "rate_limit",
            "candle_source_mode",
            "market_types",
            "is_active",
        ]


@admin.register(Exchange)
class ExchangeAdmin(admin.ModelAdmin):
    form = ExchangeAdminForm
    list_display = [
        "name",
        "class_name",
        "candle_source_mode",
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
        "candle_source_mode",
    ]
    actions = [
        "sync_trading_pairs",
    ]

    @admin.action(description="Загрузить торговые пары с биржи")
    def sync_trading_pairs(
        self, request: HttpRequest, queryset: QuerySet[Exchange]
    ) -> None:
        tasks = group(
            exchange_sync_trading_pairs.s(exchange.id) for exchange in queryset
        )
        tasks.apply_async()

        self.message_user(
            request,
            f"Запущена загрузка торговых пар для {queryset.count()} бирж(и)",
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
