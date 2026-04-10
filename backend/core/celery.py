import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

app = Celery("core")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


app.conf.beat_schedule = {
    "exchanges_sync_all_trading_pairs": {
        "task": "exchanges.tasks.exchanges_sync_all_trading_pairs",
        "schedule": crontab(hour=0, minute=0),
    },
    "traders_daily_report": {
        "task": "traders.tasks.traders.traders_daily_report",
        "schedule": crontab(hour=10, minute=0),
    },
    "arbitrage_traders_daily_report": {
        "task": "arbitrage_traders.tasks.traders.arbitrage_traders_daily_report",
        "schedule": crontab(hour=10, minute=0),
    },
    "candle_sources_fetch_last_candles": {
        "task": "candle_sources.tasks.candle_sources_fetch_last_candles",
        "schedule": crontab(minute="*"),
    },
    "exchange_client_sync_open_orders": {
        "task": "exchange_clients.tasks.exchange_client_sync_open_orders",
        "schedule": crontab(minute="*"),
    },
}
