"""
Django Admin для CandleProvider.
"""

from django.contrib import admin

from .models import CandleProvider


@admin.register(CandleProvider)
class CandleProviderAdmin(admin.ModelAdmin):
    """Admin для управления провайдерами свечей"""

    list_display = [
        "timeframe",
        "trading_pair",
        "first_source",
        "second_source",
        "is_active",
        "created_at",
    ]

    list_filter = [
        "class_name",
        "is_active",
        "first_source__timeframe",
        "created_at",
    ]

    search_fields = [
        "first_source__exchange_client__exchange__name",
        "second_source__exchange_client__exchange__name",
    ]

    readonly_fields = [
        "created_at",
        "updated_at",
    ]

    def get_queryset(self, request):
        """Оптимизация запросов"""
        qs = super().get_queryset(request)
        return qs.select_related(
            "first_source__exchange_client__exchange",
            "first_source__trading_pair",
            "second_source__exchange_client__exchange",
            "second_source__trading_pair",
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Оптимизация выпадающих списков"""
        if db_field.name in ("first_source", "second_source"):
            kwargs["queryset"] = db_field.related_model.objects.select_related(
                "exchange_client__exchange", "trading_pair"
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
