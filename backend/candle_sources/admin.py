from datetime import timedelta

from admin_auto_filters.filters import AutocompleteFilter
from celery import group
from django.conf import settings
from django.contrib import admin, messages
from django.db import models
from django.db.models import Count
from django.utils import timezone

from candle_sources.models import CandleSource, CandleSourceError
from candle_sources.tasks import source_sync_candles


class ExchangeClientFilter(AutocompleteFilter):
    title = "Exchange Client"
    field_name = "exchange_client"


class TradingPairFilter(AutocompleteFilter):
    title = "Trading Pair"
    field_name = "trading_pair"


@admin.register(CandleSourceError)
class CandleSourceErrorAdmin(admin.ModelAdmin):
    readonly_fields = [
        "candle_source",
        "type",
        "message",
        "traceback",
        "created_at",
        "updated_at",
    ]


class CandleSourceErrorInline(admin.TabularInline):
    model = CandleSourceError
    extra = 0
    max_num = settings.ADMIN_INLINE_MAX_NUM
    readonly_fields = ["type", "message", "traceback", "created_at"]
    fields = ["type", "message", "created_at"]
    show_change_link = True

    def get_queryset(self, request):
        return super().get_queryset(request).order_by("-created_at")


@admin.register(CandleSource)
class CandleSourceAdmin(admin.ModelAdmin):
    readonly_fields = ["last_synced"]
    inlines = [CandleSourceErrorInline]
    list_display = [
        "exchange_client",
        "timeframe",
        "trading_pair",
        "mode",
        "candles_count",
        "errors_count",
        "last_synced",
        "is_active",
    ]
    list_filter = [
        "is_active",
        ExchangeClientFilter,
        TradingPairFilter,
        "timeframe",
        "mode",
    ]
    search_fields = [
        "exchange_client__name",
    ]
    list_select_related = [
        "exchange_client__exchange",
        "trading_pair",
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_errors_count=Count("errors"))

    @admin.display(description="Кол-во свечей")
    def candles_count(self, obj):
        return obj.get_candles_count()

    @admin.display(description="Кол-во ошибок", ordering="_errors_count")
    def errors_count(self, obj):
        return obj._errors_count

    actions = [
        "activate_sources",
        "deactivate_sources",
        "sync_candles_one_year",
        "sync_candles_six_month",
        "sync_candles_tree_month",
        "sync_candles_one_month",
        "delete_candles_by_source",
        "clear_errors",
        "clear_all_data",
    ]

    @admin.action(description="Активировать источники")
    def activate_sources(
        self,
        request,
        queryset: models.QuerySet[CandleSource],
    ):
        for source in queryset:
            source.activate()
        self.message_user(
            request,
            f"{queryset.count()} источник(ов) активирован(ы).",
            level=messages.SUCCESS,
        )

    @admin.action(description="Деактивировать источники")
    def deactivate_sources(
        self,
        request,
        queryset: models.QuerySet[CandleSource],
    ):
        for source in queryset:
            source.deactivate()
        self.message_user(
            request,
            f"{queryset.count()} источник(ов) деактивирован(ы).",
            level=messages.SUCCESS,
        )

    @admin.action(description="Сохранить свечи за 1 год")
    def sync_candles_one_year(
        self,
        request,
        queryset: models.QuerySet[CandleSource],
    ):
        since = timezone.now() - timedelta(days=365)
        tasks = group(
            source_sync_candles.s(source_id=source.pk, since=since)
            for source in queryset
        )
        tasks.apply_async()

        self.message_user(
            request,
            (
                "Запущена задача для сохранения свечей за 1 год для "
                f"{queryset.count()} источников."
            ),
            level=messages.SUCCESS,
        )

    @admin.action(description="Сохранить свечи за 6 месяцев")
    def sync_candles_six_month(
        self,
        request,
        queryset: models.QuerySet[CandleSource],
    ):
        since = timezone.now() - timedelta(days=180)
        tasks = group(
            source_sync_candles.s(source_id=source.pk, since=since)
            for source in queryset
        )
        tasks.apply_async()

        self.message_user(
            request,
            (
                "Запущена задача для сохранения свечей за 6 месяцев для "
                f"{queryset.count()} источников."
            ),
            level=messages.SUCCESS,
        )

    @admin.action(description="Сохранить свечи за 3 месяца")
    def sync_candles_tree_month(
        self,
        request,
        queryset: models.QuerySet[CandleSource],
    ):
        since = timezone.now() - timedelta(days=90)
        tasks = group(
            source_sync_candles.s(source_id=source.pk, since=since)
            for source in queryset
        )
        tasks.apply_async()

        self.message_user(
            request,
            (
                "Запущена задача для сохранения свечей за 3 месяца для "
                f"{queryset.count()} источников."
            ),
            level=messages.SUCCESS,
        )

    @admin.action(description="Сохранить свечи за 1 месяц")
    def sync_candles_one_month(
        self,
        request,
        queryset: models.QuerySet[CandleSource],
    ):
        since = timezone.now() - timedelta(days=30)
        tasks = group(
            source_sync_candles.s(source_id=source.pk, since=since)
            for source in queryset
        )
        tasks.apply_async()

        self.message_user(
            request,
            (
                "Запущена задача для сохранения свечей за 1 месяц для "
                f"{queryset.count()} источников."
            ),
            level=messages.SUCCESS,
        )

    @admin.action(description="Удалить все свечи источника")
    def delete_candles_by_source(
        self,
        request,
        queryset: models.QuerySet[CandleSource],
    ):
        for source in queryset:
            source.delete_all_candles()

        self.message_user(
            request,
            f"Удалены все свечи у {queryset.count()} источников.",
            level=messages.SUCCESS,
        )

    @admin.action(description="Очистить все ошибки")
    def clear_errors(
        self,
        request,
        queryset: models.QuerySet[CandleSource],
    ):
        deleted_count = CandleSourceError.objects.filter(
            candle_source__in=queryset
        ).delete()[0]

        self.message_user(
            request,
            (f"Удалено {deleted_count} ошибок у {queryset.count()} источников."),
            level=messages.SUCCESS,
        )

    @admin.action(description="Очистка всех данных источника")
    def clear_all_data(
        self,
        request,
        queryset: models.QuerySet[CandleSource],
    ):
        for source in queryset:
            source.clear_all_data()

        self.message_user(
            request,
            f"Очищены все данные у {queryset.count()} источников.",
            level=messages.SUCCESS,
        )
