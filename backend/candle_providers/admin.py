"""
Django Admin для CandleProvider.
"""

from django.contrib import admin
from django.utils.html import format_html

from .models import CandleProvider


@admin.register(CandleProvider)
class CandleProviderAdmin(admin.ModelAdmin):
    """Admin для управления провайдерами свечей"""

    list_display = [
        'class_name_badge',
        'timeframe',
        'trading_pair',
        'primary_exchange',
        'second_exchange',
        'is_active',
        'created_at',
    ]

    list_filter = [
        'class_name',
        'is_active',
        'primary_source__timeframe',
        'created_at',
    ]

    search_fields = [
        'primary_source__exchange_client__exchange__name',
        'second_source__exchange_client__exchange__name',
    ]

    readonly_fields = [
        'created_at',
        'updated_at',
        'provider_info',
    ]

    fieldsets = [
        ('Basic Information', {
            'fields': [
                'class_name',
                'is_active',
            ]
        }),
        ('Exchange Sources', {
            'fields': [
                'primary_source',
                'second_source',
            ]
        }),
        ('Provider Info', {
            'fields': [
                'provider_info',
            ],
            'classes': ['collapse'],
        }),
        ('Timestamps', {
            'fields': [
                'created_at',
                'updated_at',
            ],
            'classes': ['collapse'],
        }),
    ]

    def class_name_badge(self, obj):
        """Цветной бейдж для класса провайдера"""
        colors = {
            'ExchangeCandleProvider': '#28a745',  # Зеленый
            'ArbitrageCandleProvider': '#007bff',  # Синий
        }
        color = colors.get(obj.class_name, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; '
            'padding: 3px 10px; border-radius: 3px;">{}</span>',
            color,
            obj.class_name
        )
    class_name_badge.short_description = 'Provider Type'

    def primary_exchange(self, obj):
        """Первая биржа"""
        return obj.primary_source.exchange_client.exchange.name
    primary_exchange.short_description = 'Primary Exchange'

    def second_exchange(self, obj):
        """Вторая биржа (для арбитража)"""
        if obj.second_source:
            return obj.second_source.exchange_client.exchange.name
        return '-'
    second_exchange.short_description = 'second Exchange'

    def provider_info(self, obj):
        """Детальная информация о провайдере"""
        info = f"""
        <table style="width: 100%; border-collapse: collapse;">
            <tr>
                <th style="text-align: left; padding: 5px; border: 1px solid #ddd;">Field</th>
                <th style="text-align: left; padding: 5px; border: 1px solid #ddd;">Value</th>
            </tr>
            <tr>
                <td style="padding: 5px; border: 1px solid #ddd;">Class Name</td>
                <td style="padding: 5px; border: 1px solid #ddd;">{obj.class_name}</td>
            </tr>
            <tr>
                <td style="padding: 5px; border: 1px solid #ddd;">Timeframe</td>
                <td style="padding: 5px; border: 1px solid #ddd;">{obj.timeframe}</td>
            </tr>
            <tr>
                <td style="padding: 5px; border: 1px solid #ddd;">Trading Pair</td>
                <td style="padding: 5px; border: 1px solid #ddd;">{obj.trading_pair}</td>
            </tr>
            <tr>
                <td style="padding: 5px; border: 1px solid #ddd;">Primary Source</td>
                <td style="padding: 5px; border: 1px solid #ddd;">{obj.primary_source}</td>
            </tr>
        """

        if obj.class_name == 'ArbitrageCandleProvider' and obj.second_source:
            info += f"""
            <tr>
                <td style="padding: 5px; border: 1px solid #ddd;">second Source</td>
                <td style="padding: 5px; border: 1px solid #ddd;">{obj.second_source}</td>
            </tr>
            <tr>
                <td style="padding: 5px; border: 1px solid #ddd;">Operation</td>
                <td style="padding: 5px; border: 1px solid #ddd;">Division (default)</td>
            </tr>
            """

        info += "</table>"
        return format_html(info)
    provider_info.short_description = 'Provider Information'

    def get_queryset(self, request):
        """Оптимизация запросов"""
        qs = super().get_queryset(request)
        return qs.select_related(
            'primary_source__exchange_client__exchange',
            'primary_source__trading_pair',
            'second_source__exchange_client__exchange',
            'second_source__trading_pair',
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Оптимизация выпадающих списков"""
        if db_field.name in ('primary_source', 'second_source'):
            kwargs['queryset'] = db_field.related_model.objects.select_related(
                'exchange_client__exchange',
                'trading_pair'
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
