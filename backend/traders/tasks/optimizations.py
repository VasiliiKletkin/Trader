import sentry_sdk
from celery import shared_task

from traders.models import TraderOptimizer


@shared_task(queue="optimizer")
def optimizer_optimize(optimizer_id: int) -> None:
    sentry_sdk.set_tag("optimizer_id", optimizer_id)
    optimizer = TraderOptimizer.objects.get(id=optimizer_id)
    optimizer.optimize()
