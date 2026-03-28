from celery import shared_task

from exchanges.models import Exchange


@shared_task
def exchange_sync_trading_pairs(exchange_id: int) -> str:
    """Загрузить торговые пары с биржи."""
    exchange = Exchange.objects.get(id=exchange_id)
    created, updated = exchange.sync_trading_pairs()
    return f"{exchange.name}: создано {created}, обновлено {updated}"
