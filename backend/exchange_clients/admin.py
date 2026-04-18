from admin_auto_filters.filters import AutocompleteFilter
from django.contrib import admin, messages
from django.db import models
from django.utils.html import escape
from django.utils.safestring import mark_safe
from rangefilter.filters import DateTimeRangeFilter

from core.utils.admin import ReadOnlyAdminMixin
from core.utils.common import format_price, format_spread
from exchange_clients.checks import run_client_checks
from exchange_clients.models import (
    ExchangeClient,
    ExchangeClientBalance,
    ExchangeClientOrder,
    ExchangeClientProxy,
)


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
        "count_traders",
        "count_arbitrage_traders",
        "created_at",
        "updated_at",
        "is_active",
    ]
    ordering = [
        "-created_at",
    ]
    actions = [
        "activate_clients",
        "deactivate_clients",
        "sync_balances",
        "check_clients",
        "delete_all_orders",
    ]
    search_fields = [
        "name",
        "exchange__name",
    ]
    list_filter = [
        "is_active",
        ExchangeFilter,
    ]
    autocomplete_fields = [
        "proxy",
    ]
    list_select_related = [
        "exchange",
    ]

    @admin.display(description="Кол-во трейдеров")
    def count_traders(self, obj: ExchangeClient):
        return obj.traders.count()

    @admin.display(description="Кол-во арб. трейдеров")
    def count_arbitrage_traders(self, obj: ExchangeClient):
        return obj.arbitrage_left_traders.count() + obj.arbitrage_right_traders.count()

    @admin.action(description="Активировать клиентов")
    def activate_clients(self, request, queryset: models.QuerySet[ExchangeClient]):
        for client in queryset:
            client.activate()
        self.message_user(
            request,
            f"{queryset.count()} клиент(ов) активирован(ы).",
            level=messages.SUCCESS,
        )

    @admin.action(description="Деактивировать клиентов")
    def deactivate_clients(self, request, queryset: models.QuerySet[ExchangeClient]):
        for client in queryset:
            client.deactivate()
        self.message_user(
            request,
            f"{queryset.count()} клиент(ов) деактивирован(ы).",
            level=messages.SUCCESS,
        )

    @admin.action(description="Обновить балансы")
    def sync_balances(self, request, queryset: models.QuerySet[ExchangeClient]):
        for client in queryset:
            for market_type in client.exchange.get_market_types():
                try:
                    balances = client.sync_balances(market_type=market_type)
                    non_zero = [b for b in balances if b.total > 0]
                    summary = ", ".join(
                        f"{b.currency}: {b.total}" for b in non_zero[:5]
                    )
                    if len(non_zero) > 5:
                        summary += f" и ещё {len(non_zero) - 5}"
                    self.message_user(
                        request,
                        (
                            f"✅ {client.name} ({market_type}): "
                            f"{summary or 'нет ненулевых балансов'}"
                        ),
                        level=messages.SUCCESS,
                    )
                except Exception as e:
                    self.message_user(
                        request,
                        f"❌ {client.name} ({market_type}): {e}",
                        level=messages.ERROR,
                    )

    @admin.action(description="Проверить клиентов")
    def check_clients(self, request, queryset: models.QuerySet[ExchangeClient]):
        for client in queryset:
            results = run_client_checks(client)

            lines = [f"<b>{escape(client.name)}</b>:"]
            for check_name, result in results.items():
                if result is None:
                    lines.append(f"&emsp;✅ {check_name}")
                elif result.startswith("OK"):
                    lines.append(f"&emsp;✅ {check_name}: {result}")
                else:
                    lines.append(f"&emsp;❌ {check_name}: {escape(result)}")

            all_passed = all(
                v is None or (v and v.startswith("OK")) for v in results.values()
            )
            level = messages.SUCCESS if all_passed else messages.ERROR
            self.message_user(
                request,
                mark_safe("<br>".join(lines)),  # nosec B703 B308
                level=level,
            )

    @admin.action(description="Удалить все ордера")
    def delete_all_orders(self, request, queryset: models.QuerySet[ExchangeClient]):
        total_orders_deleted = 0

        for client in queryset:
            orders_deleted, _ = client.orders.all().delete()
            total_orders_deleted += orders_deleted

        self.message_user(
            request,
            (f"✅ Удалено {total_orders_deleted} ордеров."),
            level=messages.SUCCESS,
        )


@admin.register(ExchangeClientBalance)
class ExchangeClientBalanceAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = [
        "exchange_client",
        "market_type",
        "currency",
        "used",
        "debt",
        "free",
        "total",
        "created_at",
        "updated_at",
    ]
    list_filter = [
        ExchangeClientFilter,
        "market_type",
        "currency",
    ]
    search_fields = [
        "currency",
    ]
    ordering = [
        "-created_at",
    ]
    autocomplete_fields = [
        "exchange_client",
    ]
    list_select_related = [
        "exchange_client",
    ]


@admin.register(ExchangeClientOrder)
class ExchangeClientOrderAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = [
        "exchange_client",
        "trading_pair",
        "side",
        "status",
        "order_amount",
        "order_price",
        "order_cost",
        "fee",
        "timestamp",
        "exchange_order_id",
    ]
    search_fields = [
        "exchange_order_id",
    ]
    list_filter = [
        ExchangeClientFilter,
        TradingPairFilter,
        ("timestamp", DateTimeRangeFilter),
        "side",
        "status",
    ]
    autocomplete_fields = [
        "exchange_client",
        "trading_pair",
    ]
    list_select_related = [
        "exchange_client",
        "trading_pair",
    ]

    @admin.display(description="Кол-во")
    def order_amount(self, obj: ExchangeClientOrder):
        return format_spread(obj.amount)

    @admin.display(description="Цена")
    def order_price(self, obj: ExchangeClientOrder):
        return format_price(obj.price)

    @admin.display(description="Стоимость")
    def order_cost(self, obj: ExchangeClientOrder):
        return format_price(obj.cost)

    actions = [
        "sync_from_exchange",
    ]

    @admin.action(description="Синхронизировать с биржей")
    def sync_from_exchange(self, request, queryset):
        for order in queryset.select_related(
            "exchange_client__exchange", "trading_pair"
        ):
            try:
                order.sync_from_exchange()
            except Exception as e:
                self.message_user(
                    request,
                    f"Ордер {order.exchange_order_id}: ошибка — {e}",
                    messages.ERROR,
                )
                continue
            self.message_user(
                request,
                f"Ордер {order.exchange_order_id}: синхронизирован",
                messages.SUCCESS,
            )


@admin.register(ExchangeClientProxy)
class ExchangeClientProxyAdmin(admin.ModelAdmin):
    list_display = [
        "protocol",
        "host",
        "port",
        "username",
        "password",
        "is_active",
    ]

    search_fields = [
        "host",
    ]
