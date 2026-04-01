import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

app = Celery("core")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


app.conf.beat_schedule = {
    "sources_fetch_last_candles": {
        "task": "candle_sources.tasks.sources_fetch_last_candles",
        "schedule": crontab(minute="*"),
        "options": {"queue": "candle_sources_fetch"},
    },
    "exchange_clients_sync_open_orders": {
        "task": "exchange_clients.tasks.sync_open_orders",
        "schedule": crontab(minute="*"),
    },
    "traders_daily_report": {
        "task": "traders.tasks.traders.traders_daily_report",
        "schedule": crontab(hour=10, minute=0),
    },
    "arbitrage_traders_daily_report": {
        "task": "arbitrage_traders.tasks.traders.arbitrage_traders_daily_report",
        "schedule": crontab(hour=10, minute=0),
    },
}
