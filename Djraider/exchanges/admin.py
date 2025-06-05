from django.contrib import admin

from .models import Exchange, TradingPair, CandleSource


@admin.register(Exchange)
class ExchangeAdmin(admin.ModelAdmin):
    pass


@admin.register(TradingPair)
class TradingPairAdmin(admin.ModelAdmin):
    pass


@admin.register(CandleSource)
class CandleSourceAdmin(admin.ModelAdmin):
    pass
