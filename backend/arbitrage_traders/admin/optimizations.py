from celery import group
from django.conf import settings
from django.contrib import admin
from django.db import models

from arbitrage_traders.models import (
    ArbitrageOptimizationAlgorithm,
    ArbitrageTraderOptimizationResult,
    ArbitrageTraderOptimizer,
    ArbitrageTraderOptimizerError,
)
from arbitrage_traders.tasks import arbitrage_optimizer_optimize


@admin.register(ArbitrageOptimizationAlgorithm)
class ArbitrageOptimizationAlgorithmAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "class_name", "created_at", "updated_at")
    search_fields = ("name",)


class ArbitrageOptimizationResultInlineAdmin(admin.TabularInline):
    model = ArbitrageTraderOptimizationResult
    extra = 0
    max_num = settings.ADMIN_INLINE_MAX_NUM
    fields = [
        "created_at",
        "pnl",
        "win_rate",
        "avg_candles_per_position",
        "pnl_r2",
        "roi",
        "sharpe",
        "total_positions",
        "strategy_arguments",
        "risk_manager_arguments",
        "duration",
    ]
    readonly_fields = [
        "created_at",
        "pnl",
        "win_rate",
        "avg_candles_per_position",
        "pnl_r2",
        "roi",
        "sharpe",
        "total_positions",
        "strategy_arguments",
        "risk_manager_arguments",
        "duration",
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).order_by("-created_at")


class ArbitrageOptimizerErrorInlineAdmin(admin.TabularInline):
    model = ArbitrageTraderOptimizerError
    extra = 0
    max_num = settings.ADMIN_INLINE_MAX_NUM
    fields = ["type", "message", "created_at"]
    readonly_fields = ["type", "message", "traceback", "created_at"]
    show_change_link = True

    def get_queryset(self, request):
        return super().get_queryset(request).order_by("-created_at")


@admin.register(ArbitrageTraderOptimizer)
class ArbitrageOptimizerAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "get_status_display",
        "algorithm",
        "strategy_class_name",
        "risk_manager_class_name",
        "initial_balance",
        "max_positions_count",
        "lookback_period",
        "created_at",
        "updated_at",
    )
    inlines = [
        ArbitrageOptimizationResultInlineAdmin,
        ArbitrageOptimizerErrorInlineAdmin,
    ]
    list_select_related = [
        "algorithm",
    ]

    autocomplete_fields = [
        "algorithm",
        "left_candle_source",
        "right_candle_source",
    ]
    list_filter = [
        "status",
    ]
    actions = [
        "optimize",
    ]

    @admin.action(description="Оптимизировать")
    def optimize(self, request, queryset: models.QuerySet[ArbitrageTraderOptimizer]):
        tasks = group(
            arbitrage_optimizer_optimize.s(optimizer_id=optimizer.pk)
            for optimizer in queryset
        )
        tasks.apply_async()

        self.message_user(
            request,
            f"Запущена оптимизация для {queryset.count()} оптимизаторов",
        )
