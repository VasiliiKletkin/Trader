from celery import shared_task
from optimizers.models import TraderOptimizer


@shared_task(queue="optimizer_optimize")
def optimizer_optimize(optimizer_id: int) -> None:
    try:
        optimizer = TraderOptimizer.objects.get(id=optimizer_id)
        optimizer.optimize()
    except TraderOptimizer.DoesNotExist:
        return
