import csv
from datetime import datetime
from django.contrib import admin, messages
from django.db import models
from django.http import HttpResponse
from traders.models import (
    Trader,
    TraderOrder,
    TraderPosition,
    TraderSignal,
    TraderState,
)
from traders.tasks import trader_reboot


@admin.register(Trader)
class TraderAdmin(admin.ModelAdmin):
    list_display = [
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
        "last_error",
    ]
    readonly_fields = [
        "last_reboot",
        "status",
        "errors",
    ]

    list_filter = [
        "favorite",
        "status",
        "timeframe",
        "strategy__class_name",
        "risk_manager__class_name",
        "trading_pair",
        "exchange_client",
    ]

    actions = [
        "enable_trader",
        "disable_trader",
        "reboot_trader",
        "clean_trader_data",
        "export_to_csv",
    ]

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

    @admin.display(description="Очистка данных трейдера")
    def clean_trader_data(self, request, queryset: models.QuerySet[Trader]):
        for trader in queryset:
            trader.clean_trader_state()
        self.message_user(
            request,
            f"{queryset.count()} трейдер(ов) очищен(ы).",
            level=messages.SUCCESS,
        )


@admin.register(TraderPosition)
class TraderPositionAdmin(admin.ModelAdmin):

    list_display = [
        "trader",
        "trader__trading_pair",
        "trader__timeframe",
        "trader__strategy__class_name",
        "trader__risk_manager__class_name",
        "get_status_display",
        "get_type_display",
        "amount",
        "open_price",
        "close_price",
        "open_value",
        "close_value",
        "stop_loss",
        "take_profit",
        "stop_loss_pct",
        "take_profit_pct",
        "pnl",
        "rr",
        "opened_at",
        "closed_at",
        "recalculated_at",
    ]

    list_filter = [
        "status",
        "type",
        "trader__trading_pair",
        "trader__timeframe",
        "trader__strategy__class_name",
        "trader__risk_manager__class_name",
        "opened_at",
        "closed_at",
    ]
    ordering = [
        "-opened_at",
    ]
    date_hierarchy = "opened_at"
    readonly_fields = [
        "recalculated_at",
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
        "trader__trading_pair",
        "trader__timeframe",
        "trader__strategy__class_name",
        "trader__risk_manager__class_name",
        "get_type_display",
        "price",
        "timestamp",
    ]

    list_filter = [
        "type",
        "trader__trading_pair",
        "trader__timeframe",
        "trader__strategy__class_name",
        "trader__risk_manager__class_name",
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
        "order__exchange_order_id",
        "order__amount",
        "order__price",
        "order__timestamp",
    ]


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
    actions = ["export_to_csv"]

    @admin.action(description="Экспорт в CSV")
    def export_to_csv(self, request, queryset: models.QuerySet[TraderState]):
        response = HttpResponse(content_type="text/csv")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"traders_states_{timestamp}.csv"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        
        writer = csv.writer(response)

        headers = [
            "timestamp",
            "candle_open",
            "candle_high",
            "candle_low",
            "candle_close",
            "candle_volume",
            "signal_type",
            "signal_data",
        ]
        writer.writerow(headers)

        for obj in queryset:
            writer.writerow(
                [
                    obj.timestamp,
                    obj.candle.open,
                    obj.candle.high,
                    obj.candle.low,
                    obj.candle.close,
                    obj.candle.volume,
                    obj.signal.type,
                    obj.signal.data,
                ]
            )
        return response
