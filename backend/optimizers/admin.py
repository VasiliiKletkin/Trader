from django.contrib import admin

from optimizers.tasks import optimizer_optimize
from optimizers.models import Optimizer, OptimizerResult
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


class OptimizerResultInlineAdmin(admin.TabularInline):
    model = OptimizerResult
    extra = 0
    fields = [
        "created_at",
        "theoretical_profit",
        "strategy_arguments",
    ]
    readonly_fields = [
        "created_at",
        "theoretical_profit",
        "strategy_arguments",
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).order_by("-created_at")


@admin.register(Optimizer)
class OptimizerAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "get_status_display",
        "exchange",
        "trading_pair",
        "timeframe",
        "strategy",
        "risk_manager",
        "initial_balance",
        "max_drawdown_pct",
        "max_positions_count",
        "created_at",
        "updated_at",
    )
    inlines = [OptimizerResultInlineAdmin]
    readonly_fields = [
        "last_reboot",
        "last_error",
        # "status",
        "errors",
    ]
    list_filter = [
        "favorite",
        "status",
        StrategyFilter,
        RiskManagerFilter,
        ExchangeTradingPairFilter,
        ExchangeFilter,
    ]
    actions = [
        "optimize",
    ]

    @admin.action(description="Оптимизировать")
    def optimize(self, request, queryset: models.QuerySet[Optimizer]):
        for optimizer in queryset:
            optimizer_optimize.delay(optimizer.id)
