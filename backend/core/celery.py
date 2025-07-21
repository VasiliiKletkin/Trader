import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

app = Celery("core")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


app.conf.beat_schedule = {
    "sources_fetch_candles": {
        "task": "exchanges.tasks.sources_fetch_last_candles",
        "schedule": crontab(minute="*"),
    },
    "traders_control_opened_positions": {
        "task": "traders.tasks.traders_check_opened_positions",
        "schedule": crontab(minute="0,5,10,15,20,25,30,35,40,45,50,55"),
    },
    "traders_handle_candle_1m": {
        "task": "traders.tasks.traders_handle_candle",
        "schedule": crontab(minute="*"),
        "args": ("1m",),
    },
    "traders_handle_candle_5m": {
        "task": "traders.tasks.traders_handle_candle",
        "schedule": crontab(minute="0,5,10,15,20,25,30,35,40,45,50,55"),
        "args": ("5m",),
    },
    "traders_handle_candle_15m": {
        "task": "traders.tasks.traders_handle_candle",
        "schedule": crontab(minute="0,15,30,45"),
        "args": ("15m",),
    },
    "traders_handle_candle_1h": {
        "task": "traders.tasks.traders_handle_candle",
        "schedule": crontab(minute=0, hour="*"),
        "args": ("1h",),
    },
    "traders_handle_candle_4h": {
        "task": "traders.tasks.traders_handle_candle",
        "schedule": crontab(minute=0, hour="0,4,8,12,16,20"),
        "args": ("4h",),
    },
    "traders_handle_candle_1d": {
        "task": "traders.tasks.traders_handle_candle",
        "schedule": crontab(minute=0, hour=0),
        "args": ("1d",),
    },
    "traders_handle_candle_1w": {
        "task": "traders.tasks.traders_handle_candle",
        "schedule": crontab(minute=0, hour=0, day_of_week="sun"),
        "args": ("1w",),
    },
}
