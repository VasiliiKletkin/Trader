"""
Запускает ArbitrageCandleProvider — сервис спаривания свечей для арбитражных трейдеров.

Подписывается на Redis Pub/Sub candle:*, буферизует left/right свечи,
при совпадении timestamp публикует готовую пару в arb_candle:{trader_id}.

Использование:
  python manage.py run_arbitrage_candle_provider
"""

import asyncio

from django.core.management.base import BaseCommand

from candle_sources.domain.arbitrage_candle_provider import (
    ArbitrageCandleProvider,
)


class Command(BaseCommand):
    help = "Сервис спаривания свечей для арбитражных трейдеров"

    def handle(self, *args, **options):
        self.stdout.write("Запуск ArbitrageCandleProvider...")
        provider = ArbitrageCandleProvider()
        asyncio.run(provider.run())
