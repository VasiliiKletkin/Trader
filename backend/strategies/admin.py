from django.contrib import admin
from strategies.models import ArbitrageStrategy, Strategy


@admin.register(Strategy)
class StrategyAdmin(admin.ModelAdmin):
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
    def get_description(self, obj: Strategy) -> str:
        return obj.get_description()


@admin.register(ArbitrageStrategy)
class ArbitrageStrategyAdmin(admin.ModelAdmin):
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
    def get_description(self, obj: ArbitrageStrategy) -> str:
        return obj.get_description()
