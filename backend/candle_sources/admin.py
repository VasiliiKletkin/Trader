from django.contrib import admin


from candle_sources.models import CandleSource


@admin.register(CandleSource)
class CandleSourceAdmin(admin.ModelAdmin):
    pass
