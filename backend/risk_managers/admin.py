from django.contrib import admin
from risk_managers import models


@admin.register(models.RiskManager)
class RiskManagerAdmin(admin.ModelAdmin):
    list_display = ("name", "class_name", "get_description")
    readonly_fields = ("get_description",)
    list_filter = ("class_name",)

    @admin.display(
        description="Описание",
    )
    def get_description(self, obj: models.RiskManager) -> str:
        return obj.get_description()
