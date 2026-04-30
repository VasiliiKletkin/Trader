import sentry_sdk
from celery import shared_task

from arbitrage_traders.models import ArbitrageTraderOptimizer


@shared_task(queue="optimizer")
def arbitrage_optimizer_optimize(optimizer_id: int) -> None:
    sentry_sdk.set_tag("optimizer_id", optimizer_id)
    sentry_sdk.set_tag("optimizer_kind", "arbitrage")
    optimizer = ArbitrageTraderOptimizer.objects.get(id=optimizer_id)
    optimizer.optimize()
