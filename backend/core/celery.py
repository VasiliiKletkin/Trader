import os

from celery import Celery
from celery.schedules import crontab


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

app = Celery("core")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


app.conf.beat_schedule = {
    # "save_messages_from_groups": {
    #     "task": "telegram_groups.tasks.save_messages_from_groups",
    #     "schedule": crontab(
    #         hour=0,
    #     ),
    # },

    # "generate_scenes_every_day": {
    #     "task": "dialogs.tasks.generate_scenes_every_day",
    #     "schedule": crontab(
    #         hour=1,
    #     ),
    # }
}
