from django.contrib import admin, messages
from traders.tasks import trader_reboot
from traders.models import Trader, TraderOrder, TraderSignal, TraderPosition
from django.db import models


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
        "last_reboot",
        "is_active",
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
        "is_active",
    ]

    actions = ["reboot_trader"]

    @admin.display(description="Pair")
    def get_trading_pair(self, obj: Trader):
        return obj.candle_source.trading_pair

    @admin.display(description="Timeframe")
    def get_timeframe(self, obj: Trader):
        return obj.candle_source.timeframe

    @admin.display(description="Client")
    def get_exchange_client(self, obj: Trader):
        return obj.candle_source.exchange_client

    @admin.display(description="Фактическая прибыль")
    def get_fact_profit(self, obj: Trader):
        return obj.get_fact_profit()

    @admin.display(description="Теоретическая прибыль")
    def get_theoretical_profit(self, obj: Trader):
        return obj.get_theoretical_profit()

    @admin.display(description="Winrate")
    def get_winrate(self, obj: Trader):
        return obj.get_winrate()

    @admin.action(description="Перезагрузить трейдер")
    def reboot_trader(self, request, queryset: models.QuerySet[Trader]):
        for trader in queryset:
            trader_reboot.delay(trader_id=trader.pk)
        self.message_user(
            request,
            f"{queryset.count()} трейдер(ов) перезагружается.",
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
