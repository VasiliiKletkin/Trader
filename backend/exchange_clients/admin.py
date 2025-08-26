from datetime import timedelta

from admin_auto_filters.filters import AutocompleteFilter
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


class ExchangeClientFilter(AutocompleteFilter):
    title = "Exchange Client"
    field_name = "exchange_client"


class ExchangeFilter(AutocompleteFilter):
    title = "Exchange"
    field_name = "exchange"


class TradingPairFilter(AutocompleteFilter):
    title = "Trading Pair"
    field_name = "trading_pair"


@admin.register(ExchangeClient)
class ExchangeClientAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "is_active",
        "demo",
        "created_at",
        "updated_at",
    ]
    ordering = [
        "-created_at",
    ]
    actions = [
        "fetch_balances",
        "test_credentials",
    ]
    search_fields = [
        "name",
    ]
    list_filter = [
        ExchangeFilter,
        "is_active",
    ]

    @admin.action(description="Обновить балансы для выбранных клиентов")
    def fetch_balances(self, request, queryset: models.QuerySet[ExchangeClient]):
        total_updated = 0

        for client_balance in queryset:
            client_balance.fetch_balances()
            total_updated += 1

        self.message_user(
            request,
            (
                "✅ Обновлено "
                f"{total_updated} балансов для {queryset.count()} клиентов."
            ),
            level="info",
        )

    @admin.action(description="Проверить API ключи у выбранных клиентов")
    def test_credentials(self, request, queryset: models.QuerySet[ExchangeClient]):
        results = []
        for client in queryset:
            try:
                exchange_instance = client.instantiate()
                ok = exchange_instance.get_balances()
                results.append((client.name, ok, None))
            except Exception as e:
                results.append((client.name, False, str(e)))

        details = "; ".join(
            [
                (f"{name}: {'OK' if ok else 'FAIL'}" + (" - " + err if err else ""))
                for name, ok, err in results
            ]
        )

        self.message_user(request, details, level="info")

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
        ExchangeClientFilter,
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
        "order_amount",
        "order_price",
        "order_volume",
        "timestamp",
        "exchange_order_id",
    ]
    search_fields = [
        "exchange_order_id",
        "id",
    ]
    list_filter = [
        ExchangeClientFilter,
        TradingPairFilter,
        ("timestamp", DateTimeRangeFilter),
        "side",
        "status",
    ]

    @admin.display(description="Кол-во")
    def order_amount(self, obj: ExchangeClientOrder):
        return round(obj.amount, 4)

    @admin.display(description="Цена")
    def order_price(self, obj: ExchangeClientOrder):
        return round(obj.price, 2)

    @admin.display(description="Объем")
    def order_volume(self, obj: ExchangeClientOrder):
        return round(obj.volume, 2)



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
        ExchangeClientFilter,
        TradingPairFilter,
        "timeframe",
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
            (
                "Запущена задача для сохранения свечей за 1 год для "
                f"{queryset.count()} источников."
            ),
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
            (
                "Запущена задача для сохранения свечей за 6 месяцев для "
                f"{queryset.count()} источников."
            ),
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
            (
                "Запущена задача для сохранения свечей за 3 месяца для "
                f"{queryset.count()} источников."
            ),
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
            (
                "Запущена задача для сохранения свечей за 1 месяц для "
                f"{queryset.count()} источников."
            ),
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
