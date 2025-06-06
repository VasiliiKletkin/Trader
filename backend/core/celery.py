import os

from celery import Celery
from celery.schedules import crontab


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

app = Celery("core")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


from celery.schedules import crontab

app.conf.beat_schedule = {
    "save_candles_1m": {
        "task": "exchanges.tasks.save_all_candles_by_candle_source",
        "schedule": crontab(minute="*"),  # Каждую минуту (0-59)
        "args": ("1m",),
    },
    "save_candles_5m": {
        "task": "exchanges.tasks.save_all_candles_by_candle_source",
        "schedule": crontab(minute="0,5,10,15,20,25,30,35,40,45,50,55"),
        "args": ("5m",),
    },
    "save_candles_15m": {
        "task": "exchanges.tasks.save_all_candles_by_candle_source",
        "schedule": crontab(minute="0,15,30,45"),
        "args": ("15m",),
    },
    "save_candles_1h": {
        "task": "exchanges.tasks.save_all_candles_by_candle_source",
        "schedule": crontab(minute=0, hour="*"),
        "args": ("1h",),
    },
    "save_candles_4h": {
        "task": "exchanges.tasks.save_all_candles_by_candle_source",
        "schedule": crontab(minute=0, hour="0,4,8,12,16,20"),
        "args": ("4h",),
    },
    "save_candles_1d": {
        "task": "exchanges.tasks.save_all_candles_by_candle_source",
        "schedule": crontab(minute=0, hour=0),
        "args": ("1d",),
    },
    "save_candles_1w": {
        "task": "exchanges.tasks.save_all_candles_by_candle_source",
        "schedule": crontab(minute=0, hour=0, day_of_week="sun"),
        "args": ("1w",),
    },
}
