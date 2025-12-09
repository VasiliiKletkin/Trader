from django.contrib import admin

from .tasks import optimizer_optimize
from optimizers.models import (
    TraderOptimizationAlgorithm,
    TraderOptimizationResult,
    TraderOptimizer,
)
from admin_auto_filters.filters import AutocompleteFilter

from django.db import models


class ExchangeTradingPairFilter(AutocompleteFilter):
    title = "Trading Pair"
    field_name = "trading_pair"


class ExchangeFilter(AutocompleteFilter):
    title = "Exchange"
    field_name = "exchange"


class RiskManagerFilter(AutocompleteFilter):
    title = "Risk Manager"
    field_name = "risk_manager"


class StrategyFilter(AutocompleteFilter):
    title = "Strategy"
    field_name = "strategy"


class TimeframeFilter(AutocompleteFilter):
    title = "Timeframe"
    field_name = "timeframe"


class OptimizationResultInlineAdmin(admin.TabularInline):
    model = TraderOptimizationResult
    extra = 0
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
        "errors",
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
        "errors",
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).order_by("-created_at")


@admin.register(TraderOptimizer)
class OptimizerAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "get_status_display",
        "algorithm",
        "exchange",
        "strategy_class_name",
        "risk_manager_class_name",
        "initial_balance",
        "max_positions_count",
        "created_at",
        "updated_at",
    )
    inlines = [OptimizationResultInlineAdmin]

    list_filter = [
        "status",
        # StrategyFilter,
        # RiskManagerFilter,
        # ExchangeTradingPairFilter,
        # ExchangeFilter,
    ]
    actions = [
        "optimize",
    ]

    @admin.action(description="Оптимизировать")
    def optimize(self, request, queryset: models.QuerySet[TraderOptimizer]):
        for optimizer in queryset:
            optimizer_optimize.delay(optimizer.id)


@admin.register(TraderOptimizationAlgorithm)
class OptimizationAlgorithmAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "created_at",
        "updated_at",
    )
    search_fields = ("name",)
