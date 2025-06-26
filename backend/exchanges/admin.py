from datetime import timedelta
from django.contrib import admin
from django.db import models

from exchanges.tasks import fetch_candles
from .models import Candle, CandleSource, ExchangeClient, ExchangeOrder
from django.utils import timezone


@admin.register(ExchangeClient)
class ExchangeClientAdmin(admin.ModelAdmin):
    actions = [
        "fetch_orders_last_thousand",
    ]

    @admin.action(description="Сохранить последние 1000 ордеров")
    def fetch_orders_last_thousand(
        self, request, queryset: models.QuerySet[ExchangeClient]
    ):
        total_saved = 0

        for client in queryset:
            orders = client.fetch_orders(limit=1000)
            total_saved += len(orders)

        self.message_user(
            request,
            f"✅ Сохранено {total_saved} ордеров для {queryset.count()} клиентов.",
            level="info",
        )


@admin.register(ExchangeOrder)
class ExchangeOrderAdmin(admin.ModelAdmin):
    pass


@admin.register(Candle)
class CandleAdmin(admin.ModelAdmin):
    pass


@admin.register(CandleSource)
class CandleSourceAdmin(admin.ModelAdmin):
    actions = [
        "fetch_candles_year",
        "fetch_candles_six_month",
        "fetch_candles_tree_month",
        "fetch_candles_one_month",
    ]

    @admin.action(description="Сохранить свечи за 1 год")
    def fetch_candles_year(
        self,
        request,
        queryset: models.QuerySet[CandleSource],
    ):
        now = timezone.now()
        since = now - timedelta(days=365)
        for source in queryset:
            fetch_candles.delay(source.pk, since=since)

        self.message_user(
            request,
            f"✅ Запущена задача для сохранения свечей за 1 год для {queryset.count()} источников.",
            level="info",
        )

    @admin.action(description="Сохранить свечи за 6 месяцев")
    def fetch_candles_six_month(
        self,
        request,
        queryset: models.QuerySet[CandleSource],
    ):
        now = timezone.now()
        since = now - timedelta(days=180)
        for source in queryset:
            fetch_candles.delay(source.pk, since=since)

        self.message_user(
            request,
            f"✅ Запущена задача для сохранения свечей за 6 месяцев для {queryset.count()} источников.",
            level="info",
        )

    @admin.action(description="Сохранить свечи за 3 месяца")
    def fetch_candles_tree_month(
        self,
        request,
        queryset: models.QuerySet[CandleSource],
    ):
        now = timezone.now()
        since = now - timedelta(days=90)
        for source in queryset:
            fetch_candles.delay(source.pk, since=since)
        self.message_user(
            request,
            f"✅ Запущена задача для сохранения свечей за 3 месяца для {queryset.count()} источников.",
            level="info",
        )

    @admin.action(description="Сохранить свечи за 1 месяц")
    def fetch_candles_one_month(
        self,
        request,
        queryset: models.QuerySet[CandleSource],
    ):
        now = timezone.now()
        since = now - timedelta(days=30)
        for source in queryset:
            fetch_candles.delay(source.pk, since=since)
        self.message_user(
            request,
            f"✅ Запущена задача для сохранения свечей за 1 месяц для {queryset.count()} источников.",
            level="info",
        )
