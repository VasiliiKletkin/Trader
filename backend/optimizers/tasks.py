from celery import shared_task
from django.db import models
from loguru import logger

from core.utils.types import OptimizerStatus
from optimizers.models import TraderOptimizer


@shared_task(queue="optimizer_optimize")
def optimizer_optimize(optimizer_id: int) -> None:
    try:
        optimizer = TraderOptimizer.objects.get(id=optimizer_id)
        optimizer.optimize()
    except TraderOptimizer.DoesNotExist:
        logger.error(f"Оптимизатор {optimizer_id} не найден")
    except Exception as e:
        logger.exception(f"Ошибка оптимизации {optimizer_id}: {e}")


@shared_task()
def optimize_old_optimizers() -> None:
    if TraderOptimizer.objects.filter(status=OptimizerStatus.REBOOTING).exists():
        logger.info("Есть активные оптимизации, пропускаем")
        return

    available_optimizer = (
        TraderOptimizer.objects.filter(traderoptimizationresult__isnull=False)
        .exclude(status=OptimizerStatus.REBOOTING)
        .annotate(last_result_date=models.Max("traderoptimizationresult__created_at"))
        .order_by("-last_result_date")
        .first()
    )

    if available_optimizer:
        logger.info(
            f"Запуск оптимизации для старого оптимизатора {available_optimizer.id}"
        )
        optimizer_optimize.delay(available_optimizer.id)
    else:
        logger.info("Нет оптимизаторов с результатами для переоптимизации")
