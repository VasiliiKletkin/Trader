from celery import shared_task

from arbitrage_traders.models import ArbitrageTraderOptimizer


@shared_task(queue="optimizer_optimize")
def arbitrage_optimizer_optimize(optimizer_id: int) -> None:
    optimizer = ArbitrageTraderOptimizer.objects.get(id=optimizer_id)
    optimizer.optimize()
