import asyncio
from decimal import Decimal

from admin_auto_filters.filters import AutocompleteFilter
from django.contrib import admin, messages
from django.db import models
from django.utils.html import escape
from django.utils.safestring import mark_safe
from rangefilter.filters import DateTimeRangeFilter

from core.utils.admin import ReadOnlyAdminMixin
from exchange_clients.domain.schemas import MarginMode
from exchange_clients.models import (
    ExchangeClient,
    ExchangeClientBalance,
    ExchangeClientOrder,
    ExchangeClientProxy,
)
from exchange_clients.schemas import OrderSide
from exchanges.domain import Timeframe
from exchanges.models import ExchangeTradingPair
from exchanges.schemas import MarketType


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

    def _check_instantiate(self, client: ExchangeClient) -> str | None:
        """Проверка создания доменного клиента."""
        try:
            client.instantiate()
            return None
        except Exception as e:
            return str(e)

    def _get_exchange_trading_pair(
        self, client: ExchangeClient, market_type: MarketType
    ) -> tuple[ExchangeTradingPair, Decimal, Decimal] | None:
        """Получает торговую пару для тест-ордера с учётом баланса.

        Получает балансы для market_type, затем ищет самую дешёвую
        пару среди валют с балансом.
        """
        balances = {
            b.currency: b.free
            for b in client.fetch_balances(market_type=market_type)
            if b.free > 0 and b.currency in ("USDT", "USDC")
        }
        if not balances:
            return None

        # Пары где баланс quote-валюты >= min_cost (или min_cost не задан)
        balance_filter = models.Q()
        for currency, free in balances.items():
            balance_filter |= models.Q(
                trading_pair__quote_currency=currency,
                min_cost__lte=free,
            ) | models.Q(
                trading_pair__quote_currency=currency,
                min_cost__isnull=True,
            )

        etps = (
            ExchangeTradingPair.active_objects.filter(
                balance_filter,
                exchange=client.exchange,
                trading_pair__type=market_type,
            )
            .select_related("trading_pair")
            .order_by("min_cost")
        )

        for etp in etps:
            rpc = client.get_rpc_client()
            candles = asyncio.run(
                rpc.fetch_candles(
                    trading_pair=etp.instantiate(),
                    timeframe=Timeframe.ONE_MINUTE,
                    limit=1,
                )
            )
            if not candles or candles[-1].close <= 0:
                continue

            last_price = candles[-1].close

            if etp.min_amount:
                amount = etp.min_amount
            elif etp.min_cost:
                amount = etp.min_cost * Decimal("1.1") / last_price
            elif etp.amount_precision:
                amount = etp.amount_precision
            else:
                continue

            if etp.amount_precision:
                amount = amount.quantize(etp.amount_precision)
                if etp.min_cost and amount * last_price < etp.min_cost:
                    amount += etp.amount_precision

            if amount <= 0:
                continue

            return etp, last_price, amount

        return None

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
        """Проверка получения балансов через RPC."""
        for market_type in client.exchange.get_market_types():
            try:
                client.sync_balances(market_type=market_type)
            except Exception as e:
                return f"{market_type}: {e}"
        return None

    def _check_create_and_close_order(self, client: ExchangeClient) -> str | None:
        """Проверка создания, получения и закрытия ордера через RPC."""
        result = None
        for market_type in client.exchange.get_market_types():
            result = self._get_exchange_trading_pair(client, market_type)
            if result:
                break
        if not result:
            return "Нет торговых пар с достаточным балансом на бирже"

        etp, price, amount = result
        trading_pair = etp.trading_pair
        cost = round(amount * price, 6)
        order_info = f"symbol={etp.symbol}, cost=${cost}"

        # Для фьючерсов настраиваем cross margin и плечо
        if trading_pair.type == MarketType.FUTURES:
            try:
                client.set_margin_mode(
                    margin_mode=MarginMode.CROSS,
                    trading_pair=trading_pair,
                )
                client.set_leverage(leverage=1, trading_pair=trading_pair)
            except Exception:
                pass  # Некоторые биржи не поддерживают или уже настроено

        try:
            buy_order = client.create_market_order(
                trading_pair=trading_pair,
                side=OrderSide.BUY,
                amount=amount,
                price=price,
            )
        except Exception as e:
            return f"Ошибка при открытии ордера ({order_info}): {e}"

        try:
            client.fetch_order(
                exchange_order_id=buy_order.exchange_order_id,
                trading_pair=trading_pair,
            )
        except Exception as e:
            return f"Ордер открыт, но ошибка при получении ({order_info}): {e}"

        try:
            sell_order = client.create_market_order(
                trading_pair=trading_pair,
                side=OrderSide.SELL,
                amount=buy_order.amount,
                price=buy_order.price,
            )
        except Exception as e:
            return f"Ордер открыт, но ошибка при закрытии ({order_info}): {e}"

        buy_url = f"/admin/exchange_clients/exchangeclientorder/{buy_order.pk}/change/"
        sell_url = (
            f"/admin/exchange_clients/exchangeclientorder/{sell_order.pk}/change/"
        )
        return (
            f"OK ({order_info}, "
            f'buy=<a href="{buy_url}">#{buy_order.pk}</a>, '
            f'sell=<a href="{sell_url}">#{sell_order.pk}</a>)'
        )

    @admin.action(description="Проверить клиентов")
    def check_clients(self, request, queryset: models.QuerySet[ExchangeClient]):
        checks = [
            ("Создание клиента", self._check_instantiate),
            ("Проверка прокси", self._check_proxy),
            ("Получение балансов", self._check_balances),
            (
                "Открытие, получение и закрытие ордера",
                self._check_create_and_close_order,
            ),
        ]

        for client in queryset:
            results: dict[str, str | None] = {}
            for check_name, check_fn in checks:
                if check_name == "Проверка прокси" and not client.proxy:
                    continue
                error = check_fn(client)
                results[check_name] = error
                if error is not None and check_name == "Создание клиента":
                    break

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
        return round(obj.amount, 4)

    @admin.display(description="Цена")
    def order_price(self, obj: ExchangeClientOrder):
        return round(obj.price, 4)

    @admin.display(description="Стоимость")
    def order_cost(self, obj: ExchangeClientOrder):
        return round(obj.cost, 4)

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
