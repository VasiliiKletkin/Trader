from datetime import timedelta
from decimal import Decimal

from admin_auto_filters.filters import AutocompleteFilter
from django.contrib import admin
from django.db.models import Count, DecimalField, IntegerField, OuterRef, Subquery
from django.db.models.expressions import RawSQL
from django.utils import timezone

from exchanges.models import (
    Exchange,
    ExchangeCandle,
    ExchangeTradingPair,
    TradingPair,
    TradingPairSpreadAnalytics,
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


@admin.register(TradingPairSpreadAnalytics)
class TradingPairSpreadAnalyticsAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "type",
        "max_spread",
        "exchanges_count",
    ]
    list_filter = [
        "type",
    ]
    ordering = [
        "-created_at",
    ]
    readonly_fields = [
        "name",
        "symbol",
        "type",
        "min_amount",
        "max_amount",
        "fee_percent",
    ]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["show_save"] = False
        extra_context["show_save_and_continue"] = False
        extra_context["show_save_and_add_another"] = False
        return super().changeform_view(request, object_id, form_url, extra_context)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        one_day_ago = timezone.now() - timedelta(days=1)

        exchanges_count_subquery = (
            ExchangeTradingPair.objects.filter(
                trading_pair=OuterRef("pk"),
            )
            .values("trading_pair")
            .annotate(cnt=Count("exchange", distinct=True))
            .values("cnt")[:1]
        )

        qs = qs.annotate(
            _max_spread=RawSQL(
                """
                SELECT MAX(sub.max_close / sub.min_close)
                FROM (
                    SELECT timestamp,
                           MAX(close) AS max_close,
                           MIN(close) AS min_close
                    FROM exchanges_exchangecandle
                    WHERE trading_pair_id = exchanges_tradingpair.id
                      AND timestamp >= %s
                      AND timeframe = '1m'
                    GROUP BY timestamp
                    HAVING MIN(close) > 0
                       AND COUNT(DISTINCT exchange_id) >= 2
                ) sub
                """,
                [one_day_ago],
                output_field=DecimalField(),
            ),
            _exchanges_count=Subquery(
                exchanges_count_subquery,
                output_field=IntegerField(),
            ),
        )
        return qs

    @admin.display(description="Макс. спред", ordering="_max_spread")
    def max_spread(self, obj):
        val = getattr(obj, "_max_spread", None)
        if val is None:
            return "—"
        return f"{Decimal(str(val)):.6f}"

    @admin.display(description="Кол-во бирж", ordering="_exchanges_count")
    def exchanges_count(self, obj):
        return getattr(obj, "_exchanges_count", 0) or 0
