from datetime import timedelta

from celery import group
from django.contrib import admin, messages
from django.db import models
from django.utils import timezone

from candle_sources.models import CandleSource
from candle_sources.tasks import exchange_client_candle_source_sync_candles


class ExchangeClientFilter(admin.SimpleListFilter):
    title = "Exchange Client"
    parameter_name = "exchange_client"

    def lookups(self, request, model_admin):
        from exchange_clients.models import ExchangeClient

        return [(ec.pk, str(ec)) for ec in ExchangeClient.objects.all()]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(exchange_client_id=self.value())


class TradingPairFilter(admin.SimpleListFilter):
    title = "Trading Pair"
    parameter_name = "trading_pair"

    def lookups(self, request, model_admin):
        from exchanges.models import TradingPair

        return [(tp.pk, str(tp)) for tp in TradingPair.objects.all()]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(trading_pair_id=self.value())


@admin.register(CandleSource)
class CandleSourceAdmin(admin.ModelAdmin):
    list_display = [
        "exchange_client",
        "timeframe",
        "trading_pair",
        "candles_count",
        "last_synced",
        "is_active",
    ]
    list_filter = [
        ExchangeClientFilter,
        TradingPairFilter,
        "timeframe",
        "is_active",
    ]

    actions = [
        "sync_candles_one_year",
        "sync_candles_six_month",
        "sync_candles_tree_month",
        "sync_candles_one_month",
        "delete_candles_by_source",
    ]

    @admin.action(description="Сохранить свечи за 1 год")
    def sync_candles_one_year(
        self,
        request,
        queryset: models.QuerySet[CandleSource],
    ):
        since = timezone.now() - timedelta(days=365)
        tasks = group(
            exchange_client_candle_source_sync_candles.s(
                source_id=source.pk, since=since
            )
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
            exchange_client_candle_source_sync_candles.s(
                source_id=source.pk, since=since
            )
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
            exchange_client_candle_source_sync_candles.s(
                source_id=source.pk, since=since
            )
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
            exchange_client_candle_source_sync_candles.s(
                source_id=source.pk, since=since
            )
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
