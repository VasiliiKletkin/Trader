from datetime import datetime
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

from core.utils.admin import ReadOnlyAdminMixin
from core.utils.common import format_pnl, format_price, format_spread
from exchanges.schemas import Timeframe
from traders.models import (
    Trader,
    TraderError,
    TraderOrder,
    TraderPosition,
    TraderSignal,
)
from traders.schemas import PositionStatus
from traders.tasks import (
    trader_clear_all_data,
    trader_clear_all_errors,
    trader_reboot,
)


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
        "get_balance",
        "fact_pnl",
        "theoretical_pnl",
        "fact_win_rate",
        "theoretical_win_rate",
        "fact_positions_count",
        "theoretical_positions_count",
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
    autocomplete_fields = [
        "candle_source",
        "exchange_client",
        "strategy",
        "risk_manager",
    ]
    list_select_related = [
        "candle_source__exchange",
        "candle_source__trading_pair",
        "exchange_client__exchange",
        "strategy",
        "risk_manager",
    ]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        qs = qs.annotate(
            # Теоретический PNL: только по позициям без реальных ордеров
            _theoretical_pnl=models.Subquery(
                TraderPosition.objects.filter(
                    trader=models.OuterRef("pk"),
                    status=PositionStatus.CLOSED,
                    orders__isnull=True,
                )
                .values("trader")
                .annotate(pnl=models.Sum(Trader.position_pnl_annotation()))
                .values("pnl")[:1]
            ),
            # Фактический PNL: по реальным ордерам закрытых позиций
            _fact_pnl=models.Subquery(
                TraderOrder.objects.filter(
                    trader=models.OuterRef("pk"),
                    position__status=PositionStatus.CLOSED,
                )
                .values("trader")
                .annotate(pnl=models.Sum(Trader.order_pnl_annotation()))
                .values("pnl")[:1]
            ),
            # Кол-во теоретических позиций (без ордеров)
            _theoretical_positions_count=models.Subquery(
                TraderPosition.objects.filter(
                    trader=models.OuterRef("pk"),
                    orders__isnull=True,
                )
                .values("trader")
                .annotate(count=models.Count("id"))
                .values("count")[:1],
                output_field=models.IntegerField(),
            ),
            # Кол-во фактических позиций (с реальными ордерами)
            _fact_positions_count=models.Subquery(
                TraderPosition.objects.filter(
                    trader=models.OuterRef("pk"),
                    orders__isnull=False,
                )
                .values("trader")
                .annotate(count=models.Count("id", distinct=True))
                .values("count")[:1],
                output_field=models.IntegerField(),
            ),
            # Win rate (теор.): доля прибыльных среди закрытых позиций без ордеров
            _theoretical_win_rate=models.Subquery(
                TraderPosition.objects.filter(
                    trader=models.OuterRef("pk"),
                    status=PositionStatus.CLOSED,
                    orders__isnull=True,
                )
                .annotate(pnl=Trader.position_pnl_annotation())
                .values("trader")
                .annotate(
                    rate=models.Avg(
                        models.Case(
                            models.When(pnl__gt=0, then=models.Value(1.0)),
                            default=models.Value(0.0),
                            output_field=models.FloatField(),
                        ),
                    ),
                )
                .values("rate")[:1],
                output_field=models.FloatField(),
            ),
            # Win rate (факт.): доля прибыльных среди закрытых позиций с ордерами
            _fact_win_rate=models.Subquery(
                TraderPosition.objects.filter(
                    trader=models.OuterRef("pk"),
                    status=PositionStatus.CLOSED,
                    id__in=TraderOrder.objects.values("position"),
                )
                .annotate(pnl=Trader.position_pnl_annotation())
                .values("trader")
                .annotate(
                    rate=models.Avg(
                        models.Case(
                            models.When(pnl__gt=0, then=models.Value(1.0)),
                            default=models.Value(0.0),
                            output_field=models.FloatField(),
                        ),
                    ),
                )
                .values("rate")[:1],
                output_field=models.FloatField(),
            ),
            # Средняя длительность позиции
            _avg_position_duration=models.Subquery(
                TraderPosition.objects.filter(
                    trader=models.OuterRef("pk"),
                    status=PositionStatus.CLOSED,
                )
                .values("trader")
                .annotate(
                    avg_dur=models.Avg(models.F("closed_at") - models.F("opened_at"))
                )
                .values("avg_dur")[:1],
                output_field=models.DurationField(),
            ),
        )
        return qs

    @admin.display(description="Баланс")
    def get_balance(self, obj: Trader):
        return format_pnl(obj.get_balance())

    @admin.display(description="Факт. PNL", ordering="_fact_pnl")
    def fact_pnl(self, obj: Trader):
        return format_pnl(obj._fact_pnl or 0)  # type: ignore[attr-defined]

    @admin.display(description="Теор. PNL", ordering="_theoretical_pnl")
    def theoretical_pnl(self, obj: Trader):
        return format_pnl(obj._theoretical_pnl or 0)  # type: ignore[attr-defined]

    @admin.display(description="Win rate (теор.)", ordering="_theoretical_win_rate")
    def theoretical_win_rate(self, obj: Trader):
        return format_pnl(obj._theoretical_win_rate or 0)  # type: ignore[attr-defined]

    @admin.display(description="Win rate (факт.)", ordering="_fact_win_rate")
    def fact_win_rate(self, obj: Trader):
        return format_pnl(obj._fact_win_rate or 0)  # type: ignore[attr-defined]

    @admin.display(
        description="Cред. кол-во свечей на позицию",
        ordering="_avg_position_duration",
    )
    def get_avg_candles_per_position(self, obj: Trader):
        if obj._avg_position_duration is None:  # type: ignore[attr-defined]
            return None
        timeframe_td = Timeframe(obj.candle_source.timeframe).timedelta()
        return format_pnl(obj._avg_position_duration / timeframe_td)  # type: ignore[attr-defined]

    @admin.display(
        description="Кол-во позиций (теор.)",
        ordering="_theoretical_positions_count",
    )
    def theoretical_positions_count(self, obj: Trader):
        return obj._theoretical_positions_count or 0  # type: ignore[attr-defined]

    @admin.display(
        description="Кол-во позиций (факт.)",
        ordering="_fact_positions_count",
    )
    def fact_positions_count(self, obj: Trader):
        return obj._fact_positions_count or 0  # type: ignore[attr-defined]

    @admin.action(description="Очистка данных трейдера")
    def clean_trader_data(self, request, queryset: models.QuerySet[Trader]):
        tasks = group(
            trader_clear_all_data.s(trader_id=trader.pk) for trader in queryset
        )
        tasks.apply_async()

        self.message_user(
            request,
            f"Запущена задача очистки данных для {queryset.count()} трейдер(ов).",
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
        tasks = group(
            trader_clear_all_errors.s(trader_id=trader.pk) for trader in queryset
        )
        tasks.apply_async()

        self.message_user(
            request,
            f"Запущена задача очистки ошибок для {queryset.count()} трейдер(ов).",
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
class TraderErrorAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
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
    def message_short(self, obj: TraderError):
        return obj.message[:100] if obj.message else ""


class TraderFilter(AutocompleteFilter):
    title = "Trader"
    field_name = "trader"


@admin.register(TraderPosition)
class TraderPositionAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = [
        "trader",
        "get_status_display",
        "get_type_display",
        "open_price",
        "open_amount",
        "close_price",
        "close_amount",
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
    list_select_related = [
        "trader",
    ]
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
class TraderSignalrAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
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
    list_select_related = [
        "trader",
    ]


@admin.register(TraderOrder)
class TraderOrderAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
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
    list_select_related = [
        "trader",
        "order__trading_pair",
    ]

    @admin.display(description="Кол-во")
    def order_amount(self, obj: TraderOrder):
        return format_spread(obj.order.amount)

    @admin.display(description="Цена")
    def order_price(self, obj: TraderOrder):
        return format_price(obj.order.price)

    @admin.display(description="Стоимость")
    def order_cost(self, obj: TraderOrder):
        return format_price(obj.order.cost)
