from django.contrib import admin, messages
from django.db import models
from traders.models import Trader, TraderOrder, TraderPosition, TraderSignal
from traders.tasks import trader_reboot


@admin.register(Trader)
class TraderAdmin(admin.ModelAdmin):
    list_display = [
        "get_status_display",
        "get_trading_pair",
        "get_timeframe",
        "get_exchange_client",
        "strategy",
        "risk_manager",
        "initial_balance",
        "get_fact_profit",
        "get_theoretical_profit",
        "get_winrate",
        "get_total_positions_count",
        "last_reboot",
    ]
    readonly_fields = [
        "last_reboot",
        "status",
    ]

    list_filter = [
        "status",
        "candle_source__trading_pair",
        "candle_source__timeframe",
        "candle_source__exchange_client",
        "strategy",
        "risk_manager",
    ]

    actions = [
        "enable_trader",
        "reboot_trader",
        "disable_trader",
    ]

    @admin.display(description="Pair")
    def get_trading_pair(self, obj: Trader):
        return obj.candle_source.trading_pair

    @admin.display(description="Timeframe")
    def get_timeframe(self, obj: Trader):
        return obj.candle_source.timeframe

    @admin.display(description="Client")
    def get_exchange_client(self, obj: Trader):
        return obj.candle_source.exchange_client

    @admin.display(description="Факт. прибыль")
    def get_fact_profit(self, obj: Trader):
        return round(obj.get_fact_profit(), 2)

    @admin.display(description="Теор. прибыль")
    def get_theoretical_profit(self, obj: Trader):
        return round(obj.get_theoretical_profit(), 2)

    @admin.display(description="Winrate")
    def get_winrate(self, obj: Trader):
        return round(obj.get_winrate(), 2)

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


@admin.register(TraderPosition)
class TraderPositionAdmin(admin.ModelAdmin):
    pass


@admin.register(TraderOrder)
class TraderOrderAdmin(admin.ModelAdmin):
    pass


@admin.register(TraderSignal)
class TraderSignalrAdmin(admin.ModelAdmin):
    pass
