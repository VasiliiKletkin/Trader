import os

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init, worker_process_shutdown

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

app = Celery("core")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@worker_process_init.connect
def close_db_on_worker_init(**kwargs):
    """Закрыть унаследованные от родителя соединения при старте воркер-процесса."""
    from django.db import connections

    for conn in connections.all():
        conn.close()


@worker_process_shutdown.connect
def close_db_on_worker_shutdown(**kwargs):
    """Закрыть соединения при завершении воркер-процесса."""
    from django.db import connections

    for conn in connections.all():
        conn.close()


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
    "exchange_clients_fetch_balances": {
        "task": "exchange_clients.tasks.exchange_clients_fetch_balances",
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
}
