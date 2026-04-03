from celery import shared_task

from traders.models import TraderOptimizer


@shared_task(queue="optimizers_optimize")
def optimizer_optimize(optimizer_id: int) -> None:
    optimizer = TraderOptimizer.objects.get(id=optimizer_id)
    optimizer.optimize()
