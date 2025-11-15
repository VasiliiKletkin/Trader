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
        "task": "exchange_clients.tasks.sources_fetch_last_candles",
        "schedule": crontab(minute="*"),
    },
    "exchange_clients_fetch_balances": {
        "task": "exchange_clients.tasks.exchange_clients_fetch_balances",
        "schedule": crontab(hour="*"),
    },
}
