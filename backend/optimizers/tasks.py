from celery import shared_task
from optimizers.models import Optimizer


# @shared_task(queue="optimize_trader")
# def optimize_trader(optimizer_id: int):
#     logger.info(f"Начало оптимизации {optimizer_id}")
#     try:
#         optimizer = Optimizer.objects.get(id=optimizer_id)
#     except Trader.DoesNotExist:
#         logger.error(f"TraderOptimizer с id {optimizer_id} не существует.")
#         return
#     optimizer.optimize()
#     logger.info(f"Завершена работа оптимизатора {optimizer_id}")
