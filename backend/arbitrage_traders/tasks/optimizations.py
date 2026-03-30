from celery import Task, shared_task
from loguru import logger

from arbitrage_traders.models import ArbitrageTraderOptimizer
from arbitrage_traders.schemas import ArbitrageOptimizerStatus


class ArbitrageOptimizerTask(Task):
    """Сбрасывает статус оптимизатора при WorkerLostError (SIGKILL/OOM).

    reject_on_worker_lost вернёт задачу в очередь,
    on_failure сбросит статус чтобы повторный запуск прошёл.
    """

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        optimizer_id = args[0] if args else kwargs.get("optimizer_id")
        if optimizer_id:
            ArbitrageTraderOptimizer.objects.filter(
                pk=optimizer_id,
                status=ArbitrageOptimizerStatus.REBOOTING,
            ).update(status=ArbitrageOptimizerStatus.ENABLED)
            logger.error(
                f"Арбитражный оптимизатор {optimizer_id}: "
                f"сброс статуса после {type(exc).__name__}"
            )


@shared_task(
    base=ArbitrageOptimizerTask,
    queue="optimizers_optimize",
    acks_late=True,
    reject_on_worker_lost=True,
)
def arbitrage_optimizer_optimize(optimizer_id: int) -> None:
    optimizer = ArbitrageTraderOptimizer.objects.get(id=optimizer_id)
    optimizer.optimize()
