import os

from celery import Celery
from celery.schedules import crontab


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

app = Celery("core")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


app.conf.beat_schedule = {
    # "save_candles_1m": {
    #     "task": "telegram_groups.tasks.save_messages_from_groups",
    #     "schedule": crontab(
    #         minute=1,
    #     ),
    # },
    "fetch_candles_5m": {
        "task": "exchanges.tasks.fetch_candles_by_timeframe",
        "schedule": crontab(minute="*/5"),
        "args": ("5m",),
    },
    # "save_candles_15m": {
    #     "task": "telegram_groups.tasks.save_messages_from_groups",
    #     "schedule": crontab(
    #         minute=15,
    #     ),
    # },
    # "save_candles_1h": {
    #     "task": "telegram_groups.tasks.save_messages_from_groups",
    #     "schedule": crontab(
    #         hour=1,
    #     ),
    # },
}
