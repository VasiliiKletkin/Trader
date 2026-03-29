from celery import shared_task

from traders.models import TraderOptimizer


@shared_task(queue="optimizers_optimize")
def optimizer_optimize(optimizer_id: int) -> None:
    optimizer = TraderOptimizer.objects.get(id=optimizer_id)
    optimizer.optimize()


# @shared_task()
# def optimize_old_optimizers() -> None:
#     if TraderOptimizer.objects.filter(status=OptimizerStatus.REBOOTING).exists():
#         logger.info("Есть активные оптимизации, пропускаем")
#         return

#     available_optimizer = (
#         TraderOptimizer.objects.filter(traderoptimizationresult__isnull=False)
#         .exclude(status=OptimizerStatus.REBOOTING)
#         .annotate(last_result_date=models.Max("traderoptimizationresult__created_at"))
#         .order_by("-last_result_date")
#         .first()
#     )

#     if available_optimizer:
#         logger.info(
#             f"Запуск оптимизации для старого оптимизатора {available_optimizer.id}"
#         )
#         optimizer_optimize.delay(available_optimizer.id)
#     else:
#         logger.info("Нет оптимизаторов с результатами для переоптимизации")
