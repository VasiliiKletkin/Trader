from decimal import Decimal

from admin_auto_filters.filters import AutocompleteFilter
from celery import group
from django.conf import settings
from django.contrib import admin, messages
from django.db import models

from arbitrage_traders.models import (
    ArbitrageTrader,
    ArbitrageTraderError,
    ArbitrageTraderPosition,
    ArbitrageTraderSignal,
)
from arbitrage_traders.schemas import ArbitragePositionStatus, ArbitragePositionType
from arbitrage_traders.tasks import (
    arbitrage_trader_clear_all_data,
    arbitrage_trader_clear_all_errors,
    arbitrage_trader_reboot,
)
from core.utils.admin import ReadOnlyAdminMixin
from core.utils.common import format_pnl
from exchange_clients.schemas import OrderSide


class RiskManagerFilter(AutocompleteFilter):
    title = "Risk Manager"
    field_name = "risk_manager"


class StrategyFilter(AutocompleteFilter):
    title = "Strategy"
    field_name = "strategy"


class ArbitrageTraderErrorInline(admin.TabularInline):
    model = ArbitrageTraderError
    extra = 0
    max_num = settings.ADMIN_INLINE_MAX_NUM
    readonly_fields = ["type", "message", "traceback", "created_at"]
    fields = ["type", "message", "created_at"]
    show_change_link = True

    def get_queryset(self, request):
        return super().get_queryset(request).order_by("-created_at")


@admin.register(ArbitrageTrader)
class ArbitrageTraderAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "get_status_display",
        "left_candle_source",
        "right_candle_source",
        "left_exchange_client",
        "right_exchange_client",
        "strategy",
        "risk_manager",
        "get_balance",
        "fact_pnl",
        "theoretical_pnl",
        "get_win_rate",
        "get_total_positions_count",
        "get_total_positions_count_with_orders",
        "get_avg_candles_per_position",
        "last_reboot",
        "favorite",
    ]
    inlines = [ArbitrageTraderErrorInline]
    readonly_fields = [
        "status",
        "last_reboot",
    ]
    list_filter = [
        "favorite",
        "status",
        StrategyFilter,
        RiskManagerFilter,
    ]
    actions = [
        "enable_trader",
        "disable_trader",
        "reboot_trader",
        "clean_trader_data",
        "close_all_opened_positions",
        "clear_all_errors",
    ]
    search_fields = [
        "id",
    ]
    autocomplete_fields = [
        "left_candle_source",
        "right_candle_source",
        "left_exchange_client",
        "right_exchange_client",
        "strategy",
        "risk_manager",
    ]
    list_select_related = [
        "left_candle_source__exchange",
        "left_candle_source__trading_pair",
        "right_candle_source__exchange",
        "right_candle_source__trading_pair",
        "left_exchange_client__exchange",
        "right_exchange_client__exchange",
        "strategy",
        "risk_manager",
    ]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        left_position_sign = models.Case(
            models.When(
                positions__left_type=ArbitragePositionType.LONG,
                then=models.Value(1),
            ),
            models.When(
                positions__left_type=ArbitragePositionType.SHORT,
                then=models.Value(-1),
            ),
            default=models.Value(0),
            output_field=models.SmallIntegerField(),
        )
        right_position_sign = models.Case(
            models.When(
                positions__right_type=ArbitragePositionType.LONG,
                then=models.Value(1),
            ),
            models.When(
                positions__right_type=ArbitragePositionType.SHORT,
                then=models.Value(-1),
            ),
            default=models.Value(0),
            output_field=models.SmallIntegerField(),
        )
        left_order_sign = models.Case(
            models.When(orders__left_order__side=OrderSide.SELL, then=models.Value(1)),
            models.When(orders__left_order__side=OrderSide.BUY, then=models.Value(-1)),
            default=models.Value(0),
            output_field=models.SmallIntegerField(),
        )
        right_order_sign = models.Case(
            models.When(orders__right_order__side=OrderSide.SELL, then=models.Value(1)),
            models.When(orders__right_order__side=OrderSide.BUY, then=models.Value(-1)),
            default=models.Value(0),
            output_field=models.SmallIntegerField(),
        )
        closed_filter = models.Q(positions__status=ArbitragePositionStatus.CLOSED)
        qs = qs.annotate(
            _theoretical_pnl=models.Subquery(
                ArbitrageTrader.objects.filter(pk=models.OuterRef("pk"))
                .annotate(
                    pnl=models.Sum(
                        left_position_sign
                        * (
                            models.F("positions__left_close_cost")
                            - models.F("positions__left_open_cost")
                        )
                        - models.F("positions__left_total_fee")
                        + right_position_sign
                        * (
                            models.F("positions__right_close_cost")
                            - models.F("positions__right_open_cost")
                        )
                        - models.F("positions__right_total_fee"),
                        filter=closed_filter,
                        default=Decimal("0.00"),
                    ),
                )
                .values("pnl")[:1]
            ),
            _fact_pnl=models.Subquery(
                ArbitrageTrader.objects.filter(pk=models.OuterRef("pk"))
                .annotate(
                    pnl=models.Sum(
                        left_order_sign * models.F("orders__left_order__cost")
                        - models.F("orders__left_order__fee")
                        + right_order_sign * models.F("orders__right_order__cost")
                        - models.F("orders__right_order__fee"),
                        filter=models.Q(
                            orders__position__status=ArbitragePositionStatus.CLOSED
                        ),
                        default=Decimal("0.00"),
                    ),
                )
                .values("pnl")[:1]
            ),
        )
        return qs

    @admin.display(description="Баланс")
    def get_balance(self, obj: ArbitrageTrader):
        return format_pnl(obj.get_balance())

    @admin.display(description="Факт. PNL", ordering="_fact_pnl")
    def fact_pnl(self, obj: ArbitrageTrader):
        return format_pnl(obj._fact_pnl or 0)  # type: ignore[attr-defined]

    @admin.display(description="Теор. PNL", ordering="_theoretical_pnl")
    def theoretical_pnl(self, obj: ArbitrageTrader):
        return format_pnl(obj._theoretical_pnl or 0)  # type: ignore[attr-defined]

    @admin.display(description="Win rate")
    def get_win_rate(self, obj: ArbitrageTrader):
        return format_pnl(obj.get_win_rate())

    @admin.display(description="Cред. кол-во свечей на позицию")
    def get_avg_candles_per_position(self, obj: ArbitrageTrader):
        avg_candles_per_position = obj.get_avg_candles_per_position()
        if avg_candles_per_position is None:
            return None
        return format_pnl(avg_candles_per_position)

    @admin.display(description="Колл-во позиций")
    def get_total_positions_count(self, obj: ArbitrageTrader):
        return obj.get_total_positions_count()

    @admin.display(description="Колл-во позиций с ордерами")
    def get_total_positions_count_with_orders(self, obj: ArbitrageTrader):
        return obj.get_total_positions_count_with_orders()

    @admin.action(description="Включить трейдеры")
    def enable_trader(self, request, queryset: models.QuerySet[ArbitrageTrader]):
        for trader in queryset:
            trader.enable()
        self.message_user(
            request,
            f"{queryset.count()} трейдер(ов) включен(ы).",
            level=messages.SUCCESS,
        )

    @admin.action(description="Выключить трейдеры")
    def disable_trader(self, request, queryset: models.QuerySet[ArbitrageTrader]):
        for trader in queryset:
            trader.disable()
        self.message_user(
            request,
            f"{queryset.count()} трейдер(ов) выключен(ы).",
            level=messages.SUCCESS,
        )

    @admin.action(description="Перезагрузить трейдеры")
    def reboot_trader(self, request, queryset: models.QuerySet[ArbitrageTrader]):
        tasks = group(
            arbitrage_trader_reboot.s(trader_id=trader.pk) for trader in queryset
        )
        tasks.apply_async()
        self.message_user(
            request,
            f"Запущена перезагрузка для {queryset.count()} трейдер(ов).",
            level=messages.SUCCESS,
        )

    @admin.action(description="Очистить данные трейдеров")
    def clean_trader_data(self, request, queryset: models.QuerySet[ArbitrageTrader]):
        tasks = group(
            arbitrage_trader_clear_all_data.s(trader_id=trader.pk)
            for trader in queryset
        )
        tasks.apply_async()

        self.message_user(
            request,
            f"Запущена задача очистки данных для {queryset.count()} трейдер(ов).",
            level=messages.SUCCESS,
        )

    @admin.action(description="Закрыть все открытые позиции")
    def close_all_opened_positions(
        self, request, queryset: models.QuerySet[ArbitrageTrader]
    ):
        for trader in queryset:
            trader.close_all_opened_positions()
        self.message_user(
            request,
            f"{queryset.count()} трейдер(ов) закрыл(и) все открытые позиции.",
            level=messages.SUCCESS,
        )

    @admin.action(description="Очистить все ошибки трейдера")
    def clear_all_errors(self, request, queryset: models.QuerySet[ArbitrageTrader]):
        tasks = group(
            arbitrage_trader_clear_all_errors.s(trader_id=trader.pk)
            for trader in queryset
        )
        tasks.apply_async()

        self.message_user(
            request,
            f"Запущена задача очистки ошибок для {queryset.count()} трейдер(ов).",
            level=messages.SUCCESS,
        )


@admin.register(ArbitrageTraderError)
class ArbitrageTraderErrorAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = [
        "id",
        "trader",
        "type",
        "message_short",
        "created_at",
    ]
    readonly_fields = [
        "trader",
        "message",
        "traceback",
        "type",
        "created_at",
        "updated_at",
    ]
    list_filter = [
        "type",
        "created_at",
    ]
    search_fields = [
        "message",
        "type",
    ]
    list_select_related = [
        "trader",
    ]

    @admin.display(description="Сообщение")
    def message_short(self, obj: ArbitrageTraderError):
        return obj.message[:100] if obj.message else ""


@admin.register(ArbitrageTraderSignal)
class ArbitrageTraderSignalAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = [
        "id",
        "trader",
        "timestamp",
        "left_type",
        "right_type",
        "left_price",
        "right_price",
    ]
    readonly_fields = [
        "trader",
        "timestamp",
        "left_type",
        "right_type",
        "left_candle",
        "right_candle",
        "left_price",
        "right_price",
        "data",
    ]
    list_filter = [
        "left_type",
        "timestamp",
    ]
    search_fields = [
        "id",
        "trader__id",
    ]
    list_select_related = [
        "trader",
    ]


@admin.register(ArbitrageTraderPosition)
class ArbitrageTraderPositionAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = [
        "id",
        "trader",
        "left_type",
        "right_type",
        "status",
        "left_open_price",
        "left_open_amount",
        "left_close_price",
        "left_close_amount",
        "right_open_price",
        "right_open_amount",
        "right_close_price",
        "right_close_amount",
        "pnl",
        "opened_at",
        "closed_at",
    ]
    readonly_fields = [
        "created_at",
        "updated_at",
    ]
    list_filter = [
        "status",
        "left_type",
        "opened_at",
        "closed_at",
    ]
    search_fields = [
        "id",
        "trader__id",
    ]
    list_select_related = [
        "trader",
    ]
