from celery import shared_task
# from optimizers.models import Optimizer


# @shared_task(queue="optimizer_optimize")
# def optimizer_optimize(optimizer_id: int) -> None:
#     try:
#         optimizer = Optimizer.objects.get(id=optimizer_id)
#         optimizer.optimize()
#     except Optimizer.DoesNotExist:
#         return
