from datetime import datetime
from decimal import Decimal
from io import BytesIO

import pandas as pd
from admin_auto_filters.filters import AutocompleteFilter
from celery import group
from django.conf import settings
from django.contrib import admin, messages
from django.db import models
from django.http import HttpResponse
from django.utils.timezone import localtime
from rangefilter.filters import DateTimeRangeFilter

from exchange_clients.schemas import OrderSide
from traders.models import (
    Trader,
    TraderError,
    TraderOrder,
    TraderPosition,
    TraderSignal,
)
from traders.schemas import PositionStatus, PositionType
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


class TraderErrorInline(admin.TabularInline):
    model = TraderError
    extra = 0
    max_num = settings.ADMIN_INLINE_MAX_NUM
    readonly_fields = ["type", "message", "traceback", "created_at"]
    fields = ["type", "message", "created_at"]
    show_change_link = True

    def get_queryset(self, request):
        return super().get_queryset(request).order_by("-created_at")


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
                                positions__type=PositionType.LONG,
                                then=models.ExpressionWrapper(
                                    (
                                        models.F("positions__close_price")
                                        - models.F("positions__open_price")
                                    )
                                    * models.F("positions__amount"),
                                    output_field=output_field,
                                ),
                            ),
                            models.When(
                                positions__type=PositionType.SHORT,
                                then=models.ExpressionWrapper(
                                    (
                                        models.F("positions__open_price")
                                        - models.F("positions__close_price")
                                    )
                                    * models.F("positions__amount"),
                                    output_field=output_field,
                                ),
                            ),
                            default=Decimal("0.00"),
                            output_field=output_field,
                        ),
                        filter=models.Q(positions__status=PositionStatus.CLOSED),
                    ),
                    fee=models.Sum(
                        "positions__total_fee",
                        filter=models.Q(positions__status=PositionStatus.CLOSED),
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
                                orders__order__side=OrderSide.SELL,
                                then=models.F("orders__order__price")
                                * models.F("orders__order__amount"),
                            ),
                            models.When(
                                orders__order__side=OrderSide.BUY,
                                then=-models.F("orders__order__price")
                                * models.F("orders__order__amount"),
                            ),
                            default=Decimal("0.00"),
                            output_field=output_field,
                        ),
                        filter=models.Q(orders__position__status=PositionStatus.CLOSED),
                    ),
                    fee=models.Sum(
                        "orders__order__fee",
                        filter=models.Q(orders__position__status=PositionStatus.CLOSED),
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
            signals = obj.signals.select_related("candle").order_by("timestamp")

            for signal in signals:
                candle = signal.candle
                data.append(
                    [
                        localtime(signal.timestamp).replace(tzinfo=None),
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
