from celery import Task, shared_task
from loguru import logger

from traders.models import TraderOptimizer
from traders.schemas import OptimizerStatus


class OptimizerTask(Task):
    """Сбрасывает статус оптимизатора при WorkerLostError (SIGKILL/OOM).

    reject_on_worker_lost вернёт задачу в очередь,
    on_failure сбросит статус чтобы повторный запуск прошёл.
    """

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        optimizer_id = args[0] if args else kwargs.get("optimizer_id")
        if optimizer_id:
            TraderOptimizer.objects.filter(
                pk=optimizer_id,
                status=OptimizerStatus.REBOOTING,
            ).update(status=OptimizerStatus.ENABLED)
            logger.error(
                f"Оптимизатор {optimizer_id}: сброс статуса после {type(exc).__name__}"
            )


@shared_task(
    base=OptimizerTask,
    queue="optimizers_optimize",
    acks_late=True,
    reject_on_worker_lost=True,
)
def optimizer_optimize(optimizer_id: int) -> None:
    optimizer = TraderOptimizer.objects.get(id=optimizer_id)
    optimizer.optimize()
