from datetime import datetime
from decimal import Decimal
from io import BytesIO

import pandas as pd
from admin_auto_filters.filters import AutocompleteFilter
from celery import group
from django.contrib import admin, messages
from django.db import models
from django.http import HttpResponse
from django.utils.timezone import localtime
from rangefilter.filters import DateTimeRangeFilter

from core.utils.types import (
    OrderSide,
    PositionStatus,
    PositionType,
)
from traders.models import (
    ArbitrageTrader,
    ArbitrageTraderError,
    ArbitrageTraderPosition,
    ArbitrageTraderSignal,
    Trader,
    TraderError,
    TraderOrder,
    TraderPosition,
    TraderSignal,
)
from traders.tasks import arbitrage_trader_reboot, trader_reboot


class ExchangeTradingPairFilter(AutocompleteFilter):
    title = "Trading Pair"
    field_name = "trading_pair"


class ExchangeClientFilter(AutocompleteFilter):
    title = "Exchange Client"
    field_name = "exchange_client"


class RiskManagerFilter(AutocompleteFilter):
    title = "Risk Manager"
    field_name = "risk_manager"


class StrategyFilter(AutocompleteFilter):
    title = "Strategy"
    field_name = "strategy"


class TimeframeFilter(AutocompleteFilter):
    title = "Timeframe"
    field_name = "timeframe"


class TraderErrorInline(admin.TabularInline):
    model = TraderError
    extra = 0
    readonly_fields = ["type", "message", "traceback", "created_at"]
    fields = ["type", "message", "created_at"]
    show_change_link = True


@admin.register(Trader)
class TraderAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "get_status_display",
        "candle_source",
        "exchange_client",
        "strategy",
        "risk_manager",
        "initial_balance",
        "fact_pnl",
        "theoretical_pnl",
        "get_win_rate",
        "get_total_positions_count",
        "get_total_positions_count_with_orders",
        "get_avg_candles_per_position",
        "last_reboot",
        "favorite",
    ]
    readonly_fields = [
        "last_reboot",
        "status",
    ]
    list_filter = [
        "favorite",
        "status",
        StrategyFilter,
        RiskManagerFilter,
        # ExchangeTradingPairFilter,
        ExchangeClientFilter,
    ]
    inlines = [TraderErrorInline]
    actions = [
        "enable_trader",
        "disable_trader",
        "reboot_trader",
        "clean_trader_data",
        "close_all_opened_positions",
        "export_to_xlsx",
        "clear_all_errors",
        "test_action",
    ]
    search_fields = [
        "id",
    ]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        output_field = models.DecimalField(max_digits=30, decimal_places=18)
        qs = qs.annotate(
            theoretical_pnl=models.Subquery(
                Trader.objects.filter(pk=models.OuterRef("pk"))
                .annotate(
                    gross_pnl=models.Sum(
                        models.Case(
                            models.When(
                                traderposition__type=PositionType.LONG,
                                then=models.ExpressionWrapper(
                                    (
                                        models.F("traderposition__close_price")
                                        - models.F("traderposition__open_price")
                                    )
                                    * models.F("traderposition__amount"),
                                    output_field=output_field,
                                ),
                            ),
                            models.When(
                                traderposition__type=PositionType.SHORT,
                                then=models.ExpressionWrapper(
                                    (
                                        models.F("traderposition__open_price")
                                        - models.F("traderposition__close_price")
                                    )
                                    * models.F("traderposition__amount"),
                                    output_field=output_field,
                                ),
                            ),
                            default=Decimal("0.00"),
                            output_field=output_field,
                        ),
                        filter=models.Q(traderposition__status=PositionStatus.CLOSED),
                    ),
                    fee=models.Sum(
                        "traderposition__total_fee",
                        filter=models.Q(traderposition__status=PositionStatus.CLOSED),
                    ),
                    pnl=models.functions.Coalesce(
                        models.F("gross_pnl") - models.F("fee"),
                        Decimal("0.00"),
                    ),
                )
                .values("pnl")[:1]
            ),
            fact_pnl=models.Subquery(
                Trader.objects.filter(pk=models.OuterRef("pk"))
                .annotate(
                    gross_pnl=models.Sum(
                        models.Case(
                            models.When(
                                traderorder__order__side=OrderSide.SELL,
                                then=models.F("traderorder__order__price")
                                * models.F("traderorder__order__amount"),
                            ),
                            models.When(
                                traderorder__order__side=OrderSide.BUY,
                                then=-models.F("traderorder__order__price")
                                * models.F("traderorder__order__amount"),
                            ),
                            default=Decimal("0.00"),
                            output_field=output_field,
                        ),
                        filter=models.Q(
                            traderorder__position__status=PositionStatus.CLOSED
                        ),
                    ),
                    fee=models.Sum(
                        "traderorder__order__fee",
                        filter=models.Q(
                            traderorder__position__status=PositionStatus.CLOSED
                        ),
                    ),
                    pnl=models.functions.Coalesce(
                        models.F("gross_pnl") - models.F("fee"),
                        Decimal("0.00"),
                    ),
                )
                .values("pnl")[:1]
            ),
        )
        return qs

    @admin.display(description="Факт. PNL", ordering="fact_pnl")
    def fact_pnl(self, obj: Trader):
        return round(obj.fact_pnl or 0, 2)

    @admin.display(description="Теор. PNL", ordering="theoretical_pnl")
    def theoretical_pnl(self, obj: Trader):
        return round(obj.theoretical_pnl or 0, 2)

    @admin.display(description="Win rate")
    def get_win_rate(self, obj: Trader):
        return round(obj.get_win_rate(), 2)

    @admin.display(description="Cред. кол-во свечей на позицию")
    def get_avg_candles_per_position(self, obj: Trader):
        avg_candles_per_position = obj.get_avg_candles_per_position()
        if avg_candles_per_position is None:
            return None
        return round(avg_candles_per_position, 2)

    @admin.display(description="Колл-во позиций")
    def get_total_positions_count(self, obj: Trader):
        return obj.get_total_positions_count()

    @admin.display(description="Колл-во позиций с ордерами")
    def get_total_positions_count_with_orders(self, obj: Trader):
        return obj.get_total_positions_count_with_orders()

    @admin.action(description="Очистка данных трейдера")
    def clean_trader_data(self, request, queryset: models.QuerySet[Trader]):
        for trader in queryset:
            trader.clear_all_data()
        self.message_user(
            request,
            f"{queryset.count()} трейдер(ов) очищен(ы).",
            level=messages.SUCCESS,
        )

    @admin.action(description="Перезагрузить трейдеры")
    def reboot_trader(self, request, queryset: models.QuerySet[Trader]):
        tasks = group(trader_reboot.s(trader_id=trader.pk) for trader in queryset)
        tasks.apply_async()

        self.message_user(
            request,
            f"Запущена перезагрузка для {queryset.count()} трейдер(ов).",
            level=messages.SUCCESS,
        )

    @admin.action(description="Включить трейдеры")
    def enable_trader(self, request, queryset: models.QuerySet[Trader]):
        for trader in queryset:
            trader.enable()
        self.message_user(
            request,
            f"{queryset.count()} трейдер(ов) включен(ы).",
            level=messages.SUCCESS,
        )

    @admin.action(description="Выключить трейдеры")
    def disable_trader(self, request, queryset: models.QuerySet[Trader]):
        for trader in queryset:
            trader.disable()
        self.message_user(
            request,
            f"{queryset.count()} трейдер(ов) выключен(ы).",
            level=messages.SUCCESS,
        )

    @admin.action(description="Очистить все ошибки трейдера")
    def clear_all_errors(self, request, queryset: models.QuerySet[Trader]):
        for trader in queryset:
            trader.clear_all_errors()
        self.message_user(
            request,
            f"{queryset.count()} трейдер(ов) очистили все ошибки.",
            level=messages.SUCCESS,
        )

    @admin.action(description="Закрыть все открытые позиции")
    def close_all_opened_positions(self, request, queryset: models.QuerySet[Trader]):
        for trader in queryset:
            trader.close_all_opened_positions()
        self.message_user(
            request,
            f"{queryset.count()} трейдер(ов) закрыл(и) все открытые позиции.",
            level=messages.SUCCESS,
        )

    @admin.action(description="Экспорт в Excel")
    def export_to_xlsx(self, request, queryset: models.QuerySet[Trader]):
        output = BytesIO()
        writer = pd.ExcelWriter(output, engine="xlsxwriter")

        columns = [
            "timestamp",
            "candle_open",
            "candle_high",
            "candle_low",
            "candle_close",
            "candle_volume",
            "signal_type",
            "signal_data",
        ]

        for obj in queryset:
            data = []
            states = obj.states.select_related("candle", "signal").order_by("timestamp")

            for state in states:
                candle = state.candle
                signal = state.signal
                data.append(
                    [
                        localtime(state.timestamp).replace(tzinfo=None),
                        candle.open,
                        candle.high,
                        candle.low,
                        candle.close,
                        candle.volume,
                        signal.type,
                        signal.data,
                    ]
                )

            df = pd.DataFrame(data, columns=columns)
            sheet_name = str(obj)[:31]
            df.to_excel(writer, sheet_name=sheet_name, index=False)

        writer.close()
        output.seek(0)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"traders_states_{timestamp}.xlsx"
        response = HttpResponse(
            output.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


@admin.register(TraderError)
class TraderErrorAdmin(admin.ModelAdmin):
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

    @admin.display(description="Сообщение")
    def message_short(self, obj: TraderError):
        return obj.message[:100] if obj.message else ""


class TraderFilter(AutocompleteFilter):
    title = "Trader"
    field_name = "trader"


@admin.register(TraderPosition)
class TraderPositionAdmin(admin.ModelAdmin):
    list_display = [
        "trader",
        "get_status_display",
        "get_type_display",
        "amount",
        "open_price",
        "close_price",
        "open_cost",
        "close_cost",
        "stop_loss",
        "take_profit",
        "stop_loss_pct",
        "take_profit_pct",
        "pnl",
        "rr",
        "opened_at",
        "closed_at",
        "recalculated_at",
        "close_reason",
    ]

    list_filter = [
        TraderFilter,
        "status",
        "type",
        "close_reason",
        "opened_at",
        "closed_at",
    ]
    ordering = [
        "-opened_at",
    ]
    date_hierarchy = "opened_at"
    readonly_fields = [
        "recalculated_at",
        "created_at",
        "updated_at",
    ]

    @admin.display(description="Статус")
    def get_status_display(self, obj: TraderPosition):
        return obj.get_status_display()

    @admin.display(description="Тип")
    def get_type_display(self, obj: TraderPosition):
        return obj.get_type_display()


@admin.register(TraderSignal)
class TraderSignalrAdmin(admin.ModelAdmin):
    date_hierarchy = "timestamp"

    list_display = [
        "trader",
        "get_type_display",
        "timestamp",
    ]

    list_filter = [
        TraderFilter,
        "type",
    ]
    ordering = [
        "-timestamp",
    ]


@admin.register(TraderOrder)
class TraderOrderAdmin(admin.ModelAdmin):
    list_display = [
        "trader",
        "order__trading_pair",
        "order__side",
        "order_amount",
        "order_price",
        "order_cost",
        "order__timestamp",
        "order__exchange_order_id",
    ]

    search_fields = [
        "order__exchange_order_id",
    ]
    list_filter = [
        TraderFilter,
        "order__side",
        ("order__timestamp", DateTimeRangeFilter),
    ]

    @admin.display(description="Кол-во")
    def order_amount(self, obj: TraderOrder):
        return round(obj.order.amount, 4)

    @admin.display(description="Цена")
    def order_price(self, obj: TraderOrder):
        return round(obj.order.price, 4)

    @admin.display(description="Стоимость")
    def order_cost(self, obj: TraderOrder):
        return round(obj.order.cost, 4)


class ArbitrageTraderErrorInline(admin.TabularInline):
    model = ArbitrageTraderError
    extra = 0
    readonly_fields = ["type", "message", "traceback", "created_at"]
    fields = ["type", "message", "created_at"]
    show_change_link = True


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
        "initial_balance",
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

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        output_field = models.DecimalField(max_digits=30, decimal_places=18)
        closed_filter = models.Q(arbitragetraderposition__status=PositionStatus.CLOSED)
        qs = qs.annotate(
            theoretical_pnl=models.Subquery(
                ArbitrageTrader.objects.filter(pk=models.OuterRef("pk"))
                .annotate(
                    left_gross=models.Sum(
                        models.Case(
                            models.When(
                                arbitragetraderposition__left_type=PositionType.LONG,
                                then=models.ExpressionWrapper(
                                    (
                                        models.F(
                                            "arbitragetraderposition__left_close_price"
                                        )
                                        - models.F(
                                            "arbitragetraderposition__left_open_price"
                                        )
                                    )
                                    * models.F("arbitragetraderposition__amount"),
                                    output_field=output_field,
                                ),
                            ),
                            models.When(
                                arbitragetraderposition__left_type=PositionType.SHORT,
                                then=models.ExpressionWrapper(
                                    (
                                        models.F(
                                            "arbitragetraderposition__left_open_price"
                                        )
                                        - models.F(
                                            "arbitragetraderposition__left_close_price"
                                        )
                                    )
                                    * models.F("arbitragetraderposition__amount"),
                                    output_field=output_field,
                                ),
                            ),
                            default=Decimal("0.00"),
                            output_field=output_field,
                        ),
                        filter=closed_filter,
                    ),
                    right_gross=models.Sum(
                        models.Case(
                            models.When(
                                arbitragetraderposition__right_type=PositionType.LONG,
                                then=models.ExpressionWrapper(
                                    (
                                        models.F(
                                            "arbitragetraderposition__right_close_price"
                                        )
                                        - models.F(
                                            "arbitragetraderposition__right_open_price"
                                        )
                                    )
                                    * models.F("arbitragetraderposition__amount"),
                                    output_field=output_field,
                                ),
                            ),
                            models.When(
                                arbitragetraderposition__right_type=PositionType.SHORT,
                                then=models.ExpressionWrapper(
                                    (
                                        models.F(
                                            "arbitragetraderposition__right_open_price"
                                        )
                                        - models.F(
                                            "arbitragetraderposition__right_close_price"
                                        )
                                    )
                                    * models.F("arbitragetraderposition__amount"),
                                    output_field=output_field,
                                ),
                            ),
                            default=Decimal("0.00"),
                            output_field=output_field,
                        ),
                        filter=closed_filter,
                    ),
                    fee=models.Sum(
                        "arbitragetraderposition__total_fee",
                        filter=closed_filter,
                    ),
                    pnl=models.functions.Coalesce(
                        models.F("left_gross")
                        + models.F("right_gross")
                        - models.F("fee"),
                        Decimal("0.00"),
                    ),
                )
                .values("pnl")[:1]
            ),
            fact_pnl=models.Subquery(
                ArbitrageTrader.objects.filter(pk=models.OuterRef("pk"))
                .annotate(
                    left_gross=models.Sum(
                        models.Case(
                            models.When(
                                arbitragetraderorder__left_order__side=OrderSide.SELL,
                                then=models.F("arbitragetraderorder__left_order__price")
                                * models.F("arbitragetraderorder__left_order__amount"),
                            ),
                            models.When(
                                arbitragetraderorder__left_order__side=OrderSide.BUY,
                                then=-models.F(
                                    "arbitragetraderorder__left_order__price"
                                )
                                * models.F("arbitragetraderorder__left_order__amount"),
                            ),
                            default=Decimal("0.00"),
                            output_field=output_field,
                        ),
                        filter=models.Q(
                            arbitragetraderorder__position__status=PositionStatus.CLOSED
                        ),
                    ),
                    right_gross=models.Sum(
                        models.Case(
                            models.When(
                                arbitragetraderorder__right_order__side=OrderSide.SELL,
                                then=models.F(
                                    "arbitragetraderorder__right_order__price"
                                )
                                * models.F("arbitragetraderorder__right_order__amount"),
                            ),
                            models.When(
                                arbitragetraderorder__right_order__side=OrderSide.BUY,
                                then=-models.F(
                                    "arbitragetraderorder__right_order__price"
                                )
                                * models.F("arbitragetraderorder__right_order__amount"),
                            ),
                            default=Decimal("0.00"),
                            output_field=output_field,
                        ),
                        filter=models.Q(
                            arbitragetraderorder__position__status=PositionStatus.CLOSED
                        ),
                    ),
                    left_fee=models.Sum(
                        "arbitragetraderorder__left_order__fee",
                        filter=models.Q(
                            arbitragetraderorder__position__status=PositionStatus.CLOSED
                        ),
                    ),
                    right_fee=models.Sum(
                        "arbitragetraderorder__right_order__fee",
                        filter=models.Q(
                            arbitragetraderorder__position__status=PositionStatus.CLOSED
                        ),
                    ),
                    pnl=models.functions.Coalesce(
                        models.F("left_gross")
                        + models.F("right_gross")
                        - models.F("left_fee")
                        - models.F("right_fee"),
                        Decimal("0.00"),
                    ),
                )
                .values("pnl")[:1]
            ),
        )
        return qs

    @admin.display(description="Факт. PNL", ordering="fact_pnl")
    def fact_pnl(self, obj: ArbitrageTrader):
        return round(obj.fact_pnl or 0, 2)

    @admin.display(description="Теор. PNL", ordering="theoretical_pnl")
    def theoretical_pnl(self, obj: ArbitrageTrader):
        return round(obj.theoretical_pnl or 0, 2)

    @admin.display(description="Win rate")
    def get_win_rate(self, obj: ArbitrageTrader):
        return round(obj.get_win_rate(), 2)

    @admin.display(description="Cред. кол-во свечей на позицию")
    def get_avg_candles_per_position(self, obj: ArbitrageTrader):
        avg_candles_per_position = obj.get_avg_candles_per_position()
        if avg_candles_per_position is None:
            return None
        return round(avg_candles_per_position, 2)

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
        for trader in queryset:
            trader.clear_all_data()
        self.message_user(
            request,
            f"{queryset.count()} трейдер(ов) очищен(ы).",
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
        for trader in queryset:
            trader.clear_all_errors()
        self.message_user(
            request,
            f"{queryset.count()} трейдер(ов) очистили все ошибки.",
            level=messages.SUCCESS,
        )


@admin.register(ArbitrageTraderError)
class ArbitrageTraderErrorAdmin(admin.ModelAdmin):
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

    @admin.display(description="Сообщение")
    def message_short(self, obj: ArbitrageTraderError):
        return obj.message[:100] if obj.message else ""


@admin.register(ArbitrageTraderSignal)
class ArbitrageTraderSignalAdmin(admin.ModelAdmin):
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


@admin.register(ArbitrageTraderPosition)
class ArbitrageTraderPositionAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "trader",
        "type",
        "status",
        "amount",
        "left_open_price",
        "left_close_price",
        "right_open_price",
        "right_close_price",
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
        "type",
        "opened_at",
        "closed_at",
    ]
    search_fields = [
        "id",
        "trader__id",
    ]
