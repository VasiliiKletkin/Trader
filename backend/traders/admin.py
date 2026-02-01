from datetime import datetime
from decimal import Decimal
from io import BytesIO

from django import forms
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
    Trader,
    TraderOrder,
    TraderSignal,
)
from traders.tasks import trader_reboot


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


@admin.register(Trader)
class TraderAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "get_status_display",
        "candle_provider",
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
        "last_error",
        "status",
        "errors",
    ]
    list_filter = [
        "favorite",
        "status",
        StrategyFilter,
        RiskManagerFilter,
        # ExchangeTradingPairFilter,
        ExchangeClientFilter,
    ]
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
        tasks = group(
            trader_reboot.s(trader_id=trader.pk) for trader in queryset
        )
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


class TraderFilter(AutocompleteFilter):
    title = "Trader"
    field_name = "trader"


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


class ArbitrageStrategyFilter(AutocompleteFilter):
    title = "Arbitrage Strategy"
    field_name = "strategy"


class FirstExchangeClientFilter(AutocompleteFilter):
    title = "First Exchange Client"
    field_name = "first_exchange_client"


class SecondExchangeClientFilter(AutocompleteFilter):
    title = "Second Exchange Client"
    field_name = "second_exchange_client"


@admin.register(ArbitrageTrader)
class ArbitrageTraderAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "get_status_display",
        "candle_provider",
        "first_exchange_client",
        "second_exchange_client",
        "strategy",
        "risk_manager",
        "initial_balance",
        "fact_pnl",
        "get_total_positions_count",
        "last_reboot",
        "favorite",
    ]
    readonly_fields = [
        "last_reboot",
        "last_error",
        "status",
        "errors",
    ]
    list_filter = [
        "favorite",
        "status",
        ArbitrageStrategyFilter,
        RiskManagerFilter,
        FirstExchangeClientFilter,
        SecondExchangeClientFilter,
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
        qs = qs.annotate(
            fact_pnl=models.Subquery(
                ArbitrageTrader.objects.filter(pk=models.OuterRef("pk"))
                .annotate(
                    first_gross_pnl=models.functions.Coalesce(
                        models.Sum(
                            models.Case(
                                models.When(
                                    arbitragetraderorder__first_order__side=OrderSide.SELL,
                                    then=models.F("arbitragetraderorder__first_order__price")
                                    * models.F("arbitragetraderorder__first_order__amount"),
                                ),
                                models.When(
                                    arbitragetraderorder__first_order__side=OrderSide.BUY,
                                    then=-models.F("arbitragetraderorder__first_order__price")
                                    * models.F("arbitragetraderorder__first_order__amount"),
                                ),
                                default=Decimal("0.00"),
                                output_field=output_field,
                            ),
                            filter=models.Q(
                                arbitragetraderorder__position__status=PositionStatus.CLOSED
                            ),
                        ),
                        Decimal("0.00"),
                    ),
                    first_fee=models.functions.Coalesce(
                        models.Sum(
                            "arbitragetraderorder__first_order__fee",
                            filter=models.Q(
                                arbitragetraderorder__position__status=PositionStatus.CLOSED
                            ),
                        ),
                        Decimal("0.00"),
                    ),
                    second_gross_pnl=models.functions.Coalesce(
                        models.Sum(
                            models.Case(
                                models.When(
                                    arbitragetraderorder__second_order__side=OrderSide.SELL,
                                    then=models.F("arbitragetraderorder__second_order__price")
                                    * models.F("arbitragetraderorder__second_order__amount"),
                                ),
                                models.When(
                                    arbitragetraderorder__second_order__side=OrderSide.BUY,
                                    then=-models.F("arbitragetraderorder__second_order__price")
                                    * models.F("arbitragetraderorder__second_order__amount"),
                                ),
                                default=Decimal("0.00"),
                                output_field=output_field,
                            ),
                            filter=models.Q(
                                arbitragetraderorder__position__status=PositionStatus.CLOSED
                            ),
                        ),
                        Decimal("0.00"),
                    ),
                    second_fee=models.functions.Coalesce(
                        models.Sum(
                            "arbitragetraderorder__second_order__fee",
                            filter=models.Q(
                                arbitragetraderorder__position__status=PositionStatus.CLOSED
                            ),
                        ),
                        Decimal("0.00"),
                    ),
                    pnl=models.F("first_gross_pnl")
                    + models.F("second_gross_pnl")
                    - models.F("first_fee")
                    - models.F("second_fee"),
                )
                .values("pnl")[:1]
            ),
        )
        return qs

    @admin.display(description="Факт. PNL", ordering="fact_pnl")
    def fact_pnl(self, obj: ArbitrageTrader):
        return round(obj.fact_pnl or 0, 2)

    @admin.display(description="Колл-во позиций")
    def get_total_positions_count(self, obj: ArbitrageTrader):
        return obj.positions.count()

    @admin.action(description="Очистка данных трейдера")
    def clean_trader_data(self, request, queryset: models.QuerySet[ArbitrageTrader]):
        for trader in queryset:
            trader.signals.delete()
            trader.positions.delete()
        self.message_user(
            request,
            f"{queryset.count()} арбитражный трейдер(ов) очищен(ы).",
            level=messages.SUCCESS,
        )

    @admin.action(description="Включить трейдеры")
    def enable_trader(self, request, queryset: models.QuerySet[ArbitrageTrader]):
        for trader in queryset:
            trader.enable()
        self.message_user(
            request,
            f"{queryset.count()} арбитражный трейдер(ов) включен(ы).",
            level=messages.SUCCESS,
        )

    @admin.action(description="Выключить трейдеры")
    def disable_trader(self, request, queryset: models.QuerySet[ArbitrageTrader]):
        for trader in queryset:
            trader.disable()
        self.message_user(
            request,
            f"{queryset.count()} арбитражный трейдер(ов) выключен(ы).",
            level=messages.SUCCESS,
        )

    @admin.action(description="Очистить все ошибки трейдера")
    def clear_all_errors(self, request, queryset: models.QuerySet[ArbitrageTrader]):
        queryset.update(errors=None)
        self.message_user(
            request,
            f"{queryset.count()} арбитражный трейдер(ов) очистили все ошибки.",
            level=messages.SUCCESS,
        )

    @admin.action(description="Перезагрузить трейдеры")
    def reboot_trader(self, request, queryset: models.QuerySet[ArbitrageTrader]):
        for trader in queryset:
            trader.reboot()
        self.message_user(
            request,
            f"Запущена перезагрузка для {queryset.count()} арбитражный трейдер(ов).",
            level=messages.SUCCESS,
        )

    @admin.action(description="Закрыть все открытые позиции")
    def close_all_opened_positions(self, request, queryset: models.QuerySet[ArbitrageTrader]):
        for trader in queryset:
            trader.close_all_opened_positions()
        self.message_user(
            request,
            f"{queryset.count()} арбитражный трейдер(ов) закрыл(и) все открытые позиции.",
            level=messages.SUCCESS,
        )
