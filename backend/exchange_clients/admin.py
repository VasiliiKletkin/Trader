from datetime import timedelta

from admin_auto_filters.filters import AutocompleteFilterFactory
from django.contrib import admin
from django.db import models
from django.utils import timezone
from exchange_clients.models import (
    ExchangeClientCandleSource,
    ExchangeClient,
    ExchangeClientBalance,
    ExchangeClientOrder,
)
from exchanges.tasks import fetch_candles_by_source
from rangefilter.filters import DateTimeRangeFilter


@admin.register(ExchangeClient)
class ExchangeClientAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "is_active",
        "created_at",
        "updated_at",
    ]
    ordering = [
        "-created_at",
    ]
    actions = [
        "fetch_balances",
    ]
    search_fields = [
        "name",
    ]

    @admin.action(description="Обновить балансы для выбранных клиентов")
    def fetch_balances(self, request, queryset: models.QuerySet[ExchangeClient]):
        total_updated = 0

        for client_balance in queryset:
            client_balance.fetch_balances()
            total_updated += 1

        self.message_user(
            request,
            f"✅ Обновлено {total_updated} балансов для {queryset.count()} клиентов.",
            level="info",
        )

    # @admin.action(description="Сохранить последние 1000 ордеров")
    # def fetch_orders_last_thousand(
    #     self, request, queryset: models.QuerySet[ExchangeClient]
    # ):
    #     total_saved = 0

    #     for client in queryset:
    #         orders = client.fetch_orders(limit=1000)
    #         total_saved += len(orders)

    #     self.message_user(
    #         request,
    #         f"✅ Сохранено {total_saved} ордеров для {queryset.count()} клиентов.",
    #         level="info",
    #     )


@admin.register(ExchangeClientBalance)
class ExchangeClientBalanceAdmin(admin.ModelAdmin):
    list_display = [
        "exchange_client",
        "currency",
        "created_at",
        "updated_at",
    ]
    list_filter = [
        "exchange_client",
        "currency",
    ]
    search_fields = [
        "exchange_client__name",
        "currency",
    ]
    ordering = [
        "-created_at",
    ]


@admin.register(ExchangeClientOrder)
class ExchangeClientOrderAdmin(admin.ModelAdmin):
    list_display = [
        "exchange_client",
        "trading_pair",
        "side",
        "status",
        "amount",
        "price",
        "timestamp",
        "exchange_order_id",
    ]
    search_fields = [
        "exchange_order_id",
        "id",
    ]
    list_filter = [
        AutocompleteFilterFactory("Exchange Client", "exchange_client"),
        ("timestamp", DateTimeRangeFilter),
    ]


@admin.register(ExchangeClientCandleSource)
class ExchangeClientCandleSourceAdmin(admin.ModelAdmin):
    list_display = [
        "exchange_client",
        "timeframe",
        "trading_pair",
        "total_candles_count",
        "is_active",
    ]
    list_filter = [
        "exchange_client",
        "timeframe",
        "trading_pair",
        "is_active",
    ]

    actions = [
        "fetch_candles_one_year",
        "fetch_candles_six_month",
        "fetch_candles_tree_month",
        "fetch_candles_one_month",
        "delete_candles_by_source",
    ]

    @admin.action(description="Сохранить свечи за 1 год")
    def fetch_candles_one_year(
        self,
        request,
        queryset: models.QuerySet[ExchangeClientCandleSource],
    ):
        now = timezone.now()
        since = now - timedelta(days=365)
        for source in queryset:
            fetch_candles_by_source.delay(source.pk, since=since)

        self.message_user(
            request,
            f"Запущена задача для сохранения свечей за 1 год для {queryset.count()} источников.",
            level="info",
        )

    @admin.action(description="Сохранить свечи за 6 месяцев")
    def fetch_candles_six_month(
        self,
        request,
        queryset: models.QuerySet[ExchangeClientCandleSource],
    ):
        now = timezone.now()
        since = now - timedelta(days=180)
        for source in queryset:
            fetch_candles_by_source.delay(source.pk, since=since)

        self.message_user(
            request,
            f"Запущена задача для сохранения свечей за 6 месяцев для {queryset.count()} источников.",
            level="info",
        )

    @admin.action(description="Сохранить свечи за 3 месяца")
    def fetch_candles_tree_month(
        self,
        request,
        queryset: models.QuerySet[ExchangeClientCandleSource],
    ):
        now = timezone.now()
        since = now - timedelta(days=90)
        for source in queryset:
            fetch_candles_by_source.delay(source.pk, since=since)
        self.message_user(
            request,
            f"Запущена задача для сохранения свечей за 3 месяца для {queryset.count()} источников.",
            level="info",
        )

    @admin.action(description="Сохранить свечи за 1 месяц")
    def fetch_candles_one_month(
        self,
        request,
        queryset: models.QuerySet[ExchangeClientCandleSource],
    ):
        now = timezone.now()
        since = now - timedelta(days=30)
        for source in queryset:
            fetch_candles_by_source.delay(source.pk, since=since)
        self.message_user(
            request,
            f"Запущена задача для сохранения свечей за 1 месяц для {queryset.count()} источников.",
            level="info",
        )

    @admin.action(description="Удалить все свечи источника")
    def delete_candles_by_source(
        self,
        request,
        queryset: models.QuerySet[ExchangeClientCandleSource],
    ):
        total = 0
        for source in queryset:
            deleted_count, _ = source.candles.delete()
            total += deleted_count

        self.message_user(
            request,
            f"Удалено {total} свечей у {queryset.count()} источников.",
            level="info",
        )
