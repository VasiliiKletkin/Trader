from django.contrib import admin

from arbitrage_traders.models import ArbitrageRiskManager


@admin.register(ArbitrageRiskManager)
class ArbitrageRiskManagerAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "class_name",
        "arguments",
        "get_description",
        "created_at",
        "updated_at",
    ]
    search_fields = [
        "name",
        "class_name",
    ]
    list_filter = [
        "class_name",
    ]
    readonly_fields = [
        "created_at",
        "updated_at",
        "get_description",
    ]

    @admin.display(
        description="Описание",
    )
    def get_description(self, obj: ArbitrageRiskManager) -> str:
        return obj.get_description()
