from datetime import datetime
from io import BytesIO

import pandas as pd
from admin_auto_filters.filters import AutocompleteFilter
from django.contrib import admin, messages
from django.db import models
from django.http import HttpResponse
from django.utils.timezone import localtime
from rangefilter.filters import DateTimeRangeFilter
from traders.models import (
    Trader,
    TraderOrder,
    TraderPosition,
    TraderSignal,
    TraderState,
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
        "trading_pair",
        "timeframe",
        "exchange_client",
        "strategy",
        "risk_manager",
        "initial_balance",
        "get_fact_profit",
        "get_theoretical_profit",
        "get_winrate",
        "get_total_positions_count",
        "get_avg_position_candles",
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
        ExchangeTradingPairFilter,
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

    @admin.action(description="Тестовое действие")
    def test_action(self, request, queryset: models.QuerySet[Trader]):
        self.message_user(
            request,
            f"{queryset.count()} трейдер(ов) выбрано.",
            level=messages.SUCCESS,
        )
        # from traders.tasks import trader_reboot

        # for trader in queryset:
        #     # trader_reboot(trader_id=trader.pk)
        #     trader.close_all_opened_positions()

    @admin.display(description="Факт. прибыль")
    def get_fact_profit(self, obj: Trader):
        return round(obj.get_fact_profit(), 2)

    @admin.display(description="Теор. прибыль")
    def get_theoretical_profit(self, obj: Trader):
        return round(obj.get_theoretical_profit(), 2)

    @admin.display(description="Winrate")
    def get_winrate(self, obj: Trader):
        return round(obj.get_winrate(), 2)

    @admin.display(description="Cред. кол-во свечей на позицию")
    def get_avg_position_candles(self, obj: Trader):
        avg_position_candles = obj.get_avg_position_candles()
        if avg_position_candles is None:
            return None
        return round(avg_position_candles, 2)

    @admin.display(description="Колл-во позиций")
    def get_total_positions_count(self, obj: Trader):
        return obj.get_total_positions_count()

    @admin.display(description="Очистка данных трейдера")
    def clean_trader_data(self, request, queryset: models.QuerySet[Trader]):
        for trader in queryset:
            trader.clear_all_data()
        self.message_user(
            request,
            f"{queryset.count()} трейдер(ов) очищен(ы) ошибки.",
            level=messages.SUCCESS,
        )

    @admin.action(description="Перезагрузить трейдеры")
    def reboot_trader(self, request, queryset: models.QuerySet[Trader]):
        for trader in queryset:
            trader_reboot.delay(trader_id=trader.pk)
        self.message_user(
            request,
            f"{queryset.count()} трейдер(ов) перезагружается.",
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
        "price",
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


@admin.register(TraderState)
class TraderStateAdmin(admin.ModelAdmin):
    list_display = [
        "trader",
        "candle",
        "signal",
        "timestamp",
    ]
    readonly_fields = [
        "timestamp",
    ]
    list_filter = [
        TraderFilter,
        ("timestamp", DateTimeRangeFilter),
    ]
