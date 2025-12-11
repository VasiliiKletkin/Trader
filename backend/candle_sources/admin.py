from django.contrib import admin

from candle_sources.models import CandleSource


@admin.register(CandleSource)
class CandleSourceAdmin(admin.ModelAdmin):
    list_display = ["id", "class_name"]
    search_fields = ["class_name"]
