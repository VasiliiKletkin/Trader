from decimal import Decimal

from admin_auto_filters.filters import AutocompleteFilter
from celery import group
from django.conf import settings
from django.contrib import admin, messages
from django.db import models
from django.db.models.functions import Coalesce

from arbitrage_traders.models import (
    ArbitrageTrader,
    ArbitrageTraderError,
    ArbitrageTraderOrder,
    ArbitrageTraderPosition,
    ArbitrageTraderSignal,
)
from arbitrage_traders.schemas import ArbitragePositionStatus
from arbitrage_traders.tasks import (
    arbitrage_trader_clear_all_data,
    arbitrage_trader_clear_all_errors,
    arbitrage_trader_reboot,
)
from core.utils.admin import ReadOnlyAdminMixin
from core.utils.common import format_pnl


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
    def has_delete_permission(self, request, obj=None):
        return True

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
        "fact_win_rate",
        "fact_positions_count",
        "theoretical_pnl",
        "theoretical_win_rate",
        "theoretical_positions_count",
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
        "left_candle_source__trading_pair__exchange",
        "right_candle_source__trading_pair__exchange",
        "left_exchange_client__exchange",
        "right_exchange_client__exchange",
        "strategy",
        "risk_manager",
    ]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        qs = qs.annotate(
            # Теоретический PNL: только по позициям без реальных ордеров
            _theoretical_pnl=Coalesce(
                models.Subquery(
                    ArbitrageTraderPosition.objects.filter(
                        trader=models.OuterRef("pk"),
                        status=ArbitragePositionStatus.CLOSED,
                        orders__isnull=True,
                    )
                    .values("trader")
                    .annotate(
                        pnl=models.Sum(ArbitrageTrader.position_pnl_annotation()),
                    )
                    .values("pnl")[:1]
                ),
                models.Value(Decimal("0.00")),
                output_field=models.DecimalField(max_digits=30, decimal_places=18),
            ),
            # Фактический PNL: по реальным ордерам закрытых позиций
            _fact_pnl=Coalesce(
                models.Subquery(
                    ArbitrageTraderOrder.objects.filter(
                        trader=models.OuterRef("pk"),
                        position__status=ArbitragePositionStatus.CLOSED,
                    )
                    .values("trader")
                    .annotate(pnl=models.Sum(ArbitrageTrader.order_pnl_annotation()))
                    .values("pnl")[:1]
                ),
                models.Value(Decimal("0.00")),
                output_field=models.DecimalField(max_digits=30, decimal_places=18),
            ),
            # Кол-во теоретических позиций (без ордеров)
            _theoretical_positions_count=Coalesce(
                models.Subquery(
                    ArbitrageTraderPosition.objects.filter(
                        trader=models.OuterRef("pk"),
                        orders__isnull=True,
                    )
                    .values("trader")
                    .annotate(count=models.Count("id"))
                    .values("count")[:1],
                    output_field=models.IntegerField(),
                ),
                models.Value(0),
                output_field=models.IntegerField(),
            ),
            # Кол-во фактических позиций (с реальными ордерами)
            _fact_positions_count=Coalesce(
                models.Subquery(
                    ArbitrageTraderPosition.objects.filter(
                        trader=models.OuterRef("pk"),
                        orders__isnull=False,
                    )
                    .values("trader")
                    .annotate(count=models.Count("id", distinct=True))
                    .values("count")[:1],
                    output_field=models.IntegerField(),
                ),
                models.Value(0),
                output_field=models.IntegerField(),
            ),
            # Win rate (теор.): доля прибыльных среди закрытых позиций без ордеров
            _theoretical_win_rate=models.Subquery(
                ArbitrageTraderPosition.objects.filter(
                    trader=models.OuterRef("pk"),
                    status=ArbitragePositionStatus.CLOSED,
                    orders__isnull=True,
                )
                .annotate(
                    pnl=ArbitrageTrader.position_pnl_annotation(),
                )
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
                ArbitrageTraderPosition.objects.filter(
                    trader=models.OuterRef("pk"),
                    status=ArbitragePositionStatus.CLOSED,
                    id__in=ArbitrageTraderOrder.objects.values("position"),
                )
                .annotate(
                    pnl=ArbitrageTrader.position_pnl_annotation(),
                )
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
                ArbitrageTraderPosition.objects.filter(
                    trader=models.OuterRef("pk"),
                    status=ArbitragePositionStatus.CLOSED,
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
    def get_balance(self, obj: ArbitrageTrader):
        return format_pnl(obj.get_balance())

    @admin.display(description="PNL (факт.)", ordering="_fact_pnl")
    def fact_pnl(self, obj: ArbitrageTrader):
        return format_pnl(obj._fact_pnl or 0)  # type: ignore[attr-defined]

    @admin.display(description="PNL (теор.)", ordering="_theoretical_pnl")
    def theoretical_pnl(self, obj: ArbitrageTrader):
        return format_pnl(obj._theoretical_pnl or 0)  # type: ignore[attr-defined]

    @admin.display(description="Win rate (факт.)", ordering="_fact_win_rate")
    def fact_win_rate(self, obj: ArbitrageTrader):
        return format_pnl(obj._fact_win_rate or 0)  # type: ignore[attr-defined]

    @admin.display(description="Win rate (теор.)", ordering="_theoretical_win_rate")
    def theoretical_win_rate(self, obj: ArbitrageTrader):
        return format_pnl(obj._theoretical_win_rate or 0)  # type: ignore[attr-defined]

    @admin.display(
        description="Cред. кол-во свечей на позицию",
        ordering="_avg_position_duration",
    )
    def get_avg_candles_per_position(self, obj: ArbitrageTrader):
        if obj._avg_position_duration is None:  # type: ignore[attr-defined]
            return None
        return format_pnl(obj._avg_position_duration / obj.timeframe.timedelta())  # type: ignore[attr-defined]

    @admin.display(
        description="Кол-во позиций (теор.)",
        ordering="_theoretical_positions_count",
    )
    def theoretical_positions_count(self, obj: ArbitrageTrader):
        return obj._theoretical_positions_count or 0  # type: ignore[attr-defined]

    @admin.display(
        description="Кол-во позиций (факт.)",
        ordering="_fact_positions_count",
    )
    def fact_positions_count(self, obj: ArbitrageTrader):
        return obj._fact_positions_count or 0  # type: ignore[attr-defined]

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
