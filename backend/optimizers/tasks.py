from celery import shared_task
from backend.core.utils.types import OptimizerStatus
from optimizers.models import TraderOptimizer
from django.db import models
import logging

logger = logging.getLogger(__name__)


@shared_task(queue="optimizer_optimize")
def optimizer_optimize(optimizer_id: int) -> None:
    try:
        optimizer = TraderOptimizer.objects.get(id=optimizer_id)
        optimizer.optimize()
    except TraderOptimizer.DoesNotExist:
        logger.warning(f"Оптимизатор с id {optimizer_id} не существует")
        return


@shared_task()
def optimize_old_optimizers() -> None:
    if TraderOptimizer.objects.filter(status=OptimizerStatus.REBOOTING).exists():
        logger.info("Есть активные оптимизации, пропускаем")
        return

    optimizer = (
        TraderOptimizer.objects.filter(traderoptimizationresult__isnull=False)
        .exclude(status=OptimizerStatus.REBOOTING)
        .annotate(last_result_date=models.Max("traderoptimizationresult__created_at"))
        .order_by("last_result_date")
        .first()
    )

    if optimizer:
        logger.info(f"Запуск оптимизации для старого оптимизатора {optimizer.id}")
        optimizer_optimize.delay(optimizer.id)
    else:
        logger.info("Нет оптимизаторов с результатами для переоптимизации")
