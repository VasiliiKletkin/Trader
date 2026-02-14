from django.contrib import admin

from traders.models import RiskManager


@admin.register(RiskManager)
class RiskManagerAdmin(admin.ModelAdmin):
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
    def get_description(self, obj: RiskManager) -> str:
        return obj.get_description()
