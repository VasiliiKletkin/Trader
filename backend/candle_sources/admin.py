from datetime import timedelta

from admin_auto_filters.filters import AutocompleteFilter
from celery import group
from django.conf import settings
from django.contrib import admin, messages
from django.db import models
from django.utils import timezone

from candle_sources.models import CandleSource, CandleSourceError
from candle_sources.tasks import (
    candle_source_clear_all_data,
    candle_source_clear_all_errors,
    candle_source_delete_candles,
    candle_source_sync_candles,
)
from core.utils.common import dt_str


class ExchangeFilter(AutocompleteFilter):
    title = "Биржа"
    field_name = "exchange"


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
    readonly_fields = ["status", "last_synced"]
    inlines = [CandleSourceErrorInline]
    list_display = [
        "exchange",
        "timeframe",
        "trading_pair",
        "errors_count",
        "last_synced_display",
        "status",
    ]
    list_filter = [
        "status",
        ExchangeFilter,
        TradingPairFilter,
        "timeframe",
    ]
    search_fields = [
        "exchange__name",
        "trading_pair__name",
    ]
    autocomplete_fields = [
        "exchange",
        "trading_pair",
    ]
    list_select_related = [
        "exchange",
        "trading_pair",
    ]

    @admin.display(description="Кол-во ошибок")
    def errors_count(self, obj: CandleSource):
        return obj.errors.count()

    @admin.display(description="Посл. синхр.", ordering="last_synced")
    def last_synced_display(self, obj: CandleSource):
        if obj.last_synced is None:
            return "—"
        return dt_str(timezone.localtime(obj.last_synced))

    actions = [
        "enable_sources",
        "disable_sources",
        "sync_candles_one_year",
        "sync_candles_six_month",
        "sync_candles_tree_month",
        "sync_candles_one_month",
        "delete_candles_one_month",
        "delete_candles_three_months",
        "delete_candles_six_months",
        "delete_candles_one_year",
        "delete_candles_two_years",
        "clear_errors",
        "clear_all_data",
    ]

    @admin.action(description="Включить источники")
    def enable_sources(
        self,
        request,
        queryset: models.QuerySet[CandleSource],
    ):
        for source in queryset:
            source.enable()
        self.message_user(
            request,
            f"{queryset.count()} источник(ов) включен(ы).",
            level=messages.SUCCESS,
        )

    @admin.action(description="Отключить источники")
    def disable_sources(
        self,
        request,
        queryset: models.QuerySet[CandleSource],
    ):
        for source in queryset:
            source.disable()
        self.message_user(
            request,
            f"{queryset.count()} источник(ов) отключен(ы).",
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
            candle_source_sync_candles.s(source_id=source.pk, since=since)
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
            candle_source_sync_candles.s(source_id=source.pk, since=since)
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
            candle_source_sync_candles.s(source_id=source.pk, since=since)
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
            candle_source_sync_candles.s(source_id=source.pk, since=since)
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

    @admin.action(description="Удалить свечи старше 1 месяца")
    def delete_candles_one_month(
        self, request, queryset: models.QuerySet[CandleSource]
    ):
        before = timezone.now() - timedelta(days=30)
        tasks = group(
            candle_source_delete_candles.s(source_id=source.pk, before=before)
            for source in queryset
        )
        tasks.apply_async()
        self.message_user(
            request,
            f"Запущена задача удаления свечей старше 1 месяца "
            f"для {queryset.count()} источников.",
            level=messages.SUCCESS,
        )

    @admin.action(description="Удалить свечи старше 3 месяцев")
    def delete_candles_three_months(
        self, request, queryset: models.QuerySet[CandleSource]
    ):
        before = timezone.now() - timedelta(days=90)
        tasks = group(
            candle_source_delete_candles.s(source_id=source.pk, before=before)
            for source in queryset
        )
        tasks.apply_async()
        self.message_user(
            request,
            f"Запущена задача удаления свечей старше 3 месяцев "
            f"для {queryset.count()} источников.",
            level=messages.SUCCESS,
        )

    @admin.action(description="Удалить свечи старше 6 месяцев")
    def delete_candles_six_months(
        self, request, queryset: models.QuerySet[CandleSource]
    ):
        before = timezone.now() - timedelta(days=180)
        tasks = group(
            candle_source_delete_candles.s(source_id=source.pk, before=before)
            for source in queryset
        )
        tasks.apply_async()
        self.message_user(
            request,
            f"Запущена задача удаления свечей старше 6 месяцев "
            f"для {queryset.count()} источников.",
            level=messages.SUCCESS,
        )

    @admin.action(description="Удалить свечи старше 1 года")
    def delete_candles_one_year(self, request, queryset: models.QuerySet[CandleSource]):
        before = timezone.now() - timedelta(days=365)
        tasks = group(
            candle_source_delete_candles.s(source_id=source.pk, before=before)
            for source in queryset
        )
        tasks.apply_async()
        self.message_user(
            request,
            f"Запущена задача удаления свечей старше 1 года "
            f"для {queryset.count()} источников.",
            level=messages.SUCCESS,
        )

    @admin.action(description="Удалить свечи старше 2 лет")
    def delete_candles_two_years(
        self, request, queryset: models.QuerySet[CandleSource]
    ):
        before = timezone.now() - timedelta(days=730)
        tasks = group(
            candle_source_delete_candles.s(source_id=source.pk, before=before)
            for source in queryset
        )
        tasks.apply_async()
        self.message_user(
            request,
            f"Запущена задача удаления свечей старше 2 лет "
            f"для {queryset.count()} источников.",
            level=messages.SUCCESS,
        )

    @admin.action(description="Очистить все ошибки")
    def clear_errors(
        self,
        request,
        queryset: models.QuerySet[CandleSource],
    ):
        tasks = group(
            candle_source_clear_all_errors.s(source_id=source.pk) for source in queryset
        )
        tasks.apply_async()

        self.message_user(
            request,
            (f"Запущена задача очистки ошибок для {queryset.count()} источников."),
            level=messages.SUCCESS,
        )

    @admin.action(description="Очистка всех данных источника")
    def clear_all_data(
        self,
        request,
        queryset: models.QuerySet[CandleSource],
    ):
        tasks = group(
            candle_source_clear_all_data.s(source_id=source.pk) for source in queryset
        )
        tasks.apply_async()

        self.message_user(
            request,
            (f"Запущена задача очистки данных для {queryset.count()} источников."),
            level=messages.SUCCESS,
        )
