from admin_auto_filters.filters import AutocompleteFilter
from django.contrib import admin, messages
from django.db import models
from django.utils.html import escape
from django.utils.safestring import mark_safe
from rangefilter.filters import DateTimeRangeFilter

from exchange_clients.models import (
    ExchangeClient,
    ExchangeClientBalance,
    ExchangeClientOrder,
    ExchangeClientProxy,
)
from exchange_clients.schemas import OrderSide
from exchanges.models import TradingPair


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
        "count_candles_sources",
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
        "fetch_balances",
        "check_clients",
        "delete_all_orders",
    ]
    search_fields = [
        "name",
    ]
    list_filter = [
        "is_active",
        ExchangeFilter,
    ]
    autocomplete_fields = [
        "proxy",
    ]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(
                _candle_sources_count=models.Count("candlesource", distinct=True),
                _traders_count=models.Count("traders", distinct=True),
                _arbitrage_traders_count=(
                    models.Count("arbitrage_left_traders", distinct=True)
                    + models.Count("arbitrage_right_traders", distinct=True)
                ),
            )
        )

    @admin.display(
        description="Кол-во источников свечей",
        ordering="_candle_sources_count",
    )
    def count_candles_sources(self, obj):
        return obj._candle_sources_count

    @admin.display(description="Кол-во трейдеров", ordering="_traders_count")
    def count_traders(self, obj):
        return obj._traders_count

    @admin.display(
        description="Кол-во арб. трейдеров",
        ordering="_arbitrage_traders_count",
    )
    def count_arbitrage_traders(self, obj):
        return obj._arbitrage_traders_count

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
    def fetch_balances(self, request, queryset: models.QuerySet[ExchangeClient]):
        for client in queryset:
            try:
                balances = client.fetch_balances()
                non_zero = [b for b in balances if b.total > 0]
                summary = ", ".join(f"{b.currency}: {b.total}" for b in non_zero[:5])
                if len(non_zero) > 5:
                    summary += f" и ещё {len(non_zero) - 5}"
                self.message_user(
                    request,
                    f"✅ {client.name}: {summary or 'нет ненулевых балансов'}",
                    level=messages.SUCCESS,
                )
            except Exception as e:
                self.message_user(
                    request,
                    f"❌ {client.name}: {e}",
                    level=messages.ERROR,
                )

    def _check_instantiate(self, client: ExchangeClient) -> str | None:
        """Проверка создания доменного клиента."""
        try:
            client.instantiate()
            return None
        except Exception as e:
            return str(e)

    def _check_proxy(self, client: ExchangeClient) -> str | None:
        """Проверка прокси-сервера."""
        if not client.proxy:
            return None
        try:
            client.proxy.check_obj()
            return client.proxy.errors or None
        except Exception as e:
            return str(e)

    def _check_balances(self, client: ExchangeClient) -> str | None:
        """Проверка получения балансов."""
        try:
            client.fetch_balances()
            return None
        except Exception as e:
            return str(e)

    def _get_btc_trading_pairs(self):
        """Получает список торговых пар BTC/USDT, BTC/USDC для fallback."""
        pairs = []
        for name in ("BTC/USDT", "BTC/USDC"):
            pair = TradingPair.objects.filter(name=name).first()
            if pair:
                pairs.append(pair)
        if not pairs:
            first = TradingPair.objects.first()
            if first:
                pairs.append(first)
        return pairs

    def _check_open_orders(self, client: ExchangeClient) -> str | None:
        """Проверка получения открытых ордеров."""
        trading_pairs = self._get_btc_trading_pairs()
        if not trading_pairs:
            return "Нет торговых пар"
        last_error = None
        for trading_pair in trading_pairs:
            try:
                client.get_open_orders(trading_pair=trading_pair)
                return None
            except Exception as e:
                last_error = str(e)
        return last_error

    def _check_create_and_close_order(self, client: ExchangeClient) -> str | None:
        """Проверка создания и закрытия ордера."""
        trading_pairs = self._get_btc_trading_pairs()
        if not trading_pairs:
            return "Нет торговых пар"

        last_error = None
        for trading_pair in trading_pairs:
            try:
                buy_order = client.create_market_order(
                    trading_pair=trading_pair,
                    side=OrderSide.BUY,
                    amount=trading_pair.min_amount,
                )
            except Exception as e:
                last_error = f"Ошибка при открытии ордера ({trading_pair}): {e}"
                continue

            try:
                client.create_market_order(
                    trading_pair=trading_pair,
                    side=OrderSide.SELL,
                    amount=buy_order.amount,
                )
            except Exception as e:
                return f"Ордер открыт, но ошибка при закрытии ({trading_pair}): {e}"

            return None

        return last_error

    @admin.action(description="Проверить клиентов")
    def check_clients(self, request, queryset: models.QuerySet[ExchangeClient]):
        checks = [
            ("Создание клиента", self._check_instantiate),
            ("Проверка прокси", self._check_proxy),
            ("Получение балансов", self._check_balances),
            ("Получение открытых ордеров", self._check_open_orders),
            ("Открытие и закрытие ордера", self._check_create_and_close_order),
        ]

        for client in queryset:
            results: dict[str, str | None] = {}
            for check_name, check_fn in checks:
                error = check_fn(client)
                if check_name == "Проверка прокси" and not client.proxy:
                    continue
                results[check_name] = error
                if error is not None:
                    break

            lines = [f"<b>{escape(client.name)}</b>:"]
            for check_name, error in results.items():
                if error is None:
                    lines.append(f"&emsp;✅ {check_name}")
                else:
                    lines.append(f"&emsp;❌ {check_name}: {escape(error)}")

            all_passed = all(v is None for v in results.values())
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
class ExchangeClientBalanceAdmin(admin.ModelAdmin):
    list_display = [
        "exchange_client",
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
class ExchangeClientOrderAdmin(admin.ModelAdmin):
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
        return round(obj.amount, 4)

    @admin.display(description="Цена")
    def order_price(self, obj: ExchangeClientOrder):
        return round(obj.price, 4)

    @admin.display(description="Стоимость")
    def order_cost(self, obj: ExchangeClientOrder):
        return round(obj.cost, 4)


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
