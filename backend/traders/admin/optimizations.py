from celery import group
from django.conf import settings
from django.contrib import admin
from django.db import models

from traders.models import (
    TraderOptimizationAlgorithm,
    TraderOptimizationResult,
    TraderOptimizer,
    TraderOptimizerError,
)
from traders.tasks import optimizer_optimize


@admin.register(TraderOptimizationAlgorithm)
class TraderOptimizationAlgorithmAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "class_name", "created_at", "updated_at")
    search_fields = ("name",)


class OptimizationResultInlineAdmin(admin.TabularInline):
    model = TraderOptimizationResult
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


class OptimizerErrorInlineAdmin(admin.TabularInline):
    model = TraderOptimizerError
    extra = 0
    max_num = settings.ADMIN_INLINE_MAX_NUM
    fields = ["type", "message", "created_at"]
    readonly_fields = ["type", "message", "traceback", "created_at"]
    show_change_link = True

    def get_queryset(self, request):
        return super().get_queryset(request).order_by("-created_at")


@admin.register(TraderOptimizer)
class OptimizerAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "get_status_display",
        "algorithm",
        "candle_source",
        "strategy_class_name",
        "risk_manager_class_name",
        "initial_balance",
        "max_positions_count",
        # "lookback_days",
        "created_at",
        "updated_at",
    )
    inlines = [OptimizationResultInlineAdmin, OptimizerErrorInlineAdmin]
    list_select_related = [
        "algorithm",
        "candle_source",
    ]

    autocomplete_fields = [
        "algorithm",
        "candle_source",
    ]
    list_filter = [
        "status",
    ]
    actions = [
        "optimize",
    ]

    @admin.action(description="Оптимизировать")
    def optimize(self, request, queryset: models.QuerySet[TraderOptimizer]):
        tasks = group(
            optimizer_optimize.s(optimizer_id=optimizer.pk) for optimizer in queryset
        )
        tasks.apply_async()

        self.message_user(
            request,
            f"Запущена оптимизация для {queryset.count()} оптимизаторов",
        )
