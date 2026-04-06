from datetime import timedelta

from admin_auto_filters.filters import AutocompleteFilter
from celery import group
from django.conf import settings
from django.contrib import admin, messages
from django.db import models
from django.utils import timezone

from candle_sources.models import CandleSource, CandleSourceError
from candle_sources.tasks import source_delete_all_candles, source_sync_candles
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
    readonly_fields = ["last_synced"]
    inlines = [CandleSourceErrorInline]
    list_display = [
        "exchange",
        "timeframe",
        "trading_pair",
        "mode_display",
        "errors_count",
        "last_synced_display",
        "is_active",
    ]
    list_filter = [
        "is_active",
        ExchangeFilter,
        TradingPairFilter,
        "timeframe",
        "mode",
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

    @admin.display(description="Режим", ordering="mode")
    def mode_display(self, obj: CandleSource):
        return obj.get_mode_display()

    @admin.display(description="Кол-во ошибок")
    def errors_count(self, obj: CandleSource):
        return obj.errors.count()

    @admin.display(description="Посл. синхр.", ordering="last_synced")
    def last_synced_display(self, obj: CandleSource):
        if obj.last_synced is None:
            return "—"
        return dt_str(timezone.localtime(obj.last_synced))

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
        tasks = group(
            source_delete_all_candles.s(source_id=source.pk) for source in queryset
        )
        tasks.apply_async()

        self.message_user(
            request,
            (f"Запущена задача удаления свечей для {queryset.count()} источников."),
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
        tasks = group(
            source_delete_all_candles.s(source_id=source.pk) for source in queryset
        )
        tasks.apply_async()

        CandleSourceError.objects.filter(candle_source__in=queryset).delete()
        queryset.update(last_synced=None)

        self.message_user(
            request,
            (f"Запущена задача очистки данных для {queryset.count()} источников."),
            level=messages.SUCCESS,
        )
