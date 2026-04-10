from celery import group, shared_task
from loguru import logger

from exchanges.models import Exchange
from exchanges.schemas import MarketType


@shared_task
def exchange_sync_trading_pairs(exchange_id: int) -> str:
    """Загрузить торговые пары с биржи."""
    exchange = Exchange.objects.get(id=exchange_id)
    total_created = 0
    total_updated = 0
    for market_type in MarketType:
        created, updated = exchange.sync_trading_pairs(
            market_type=market_type,
        )
        total_created += created
        total_updated += updated
    return f"{exchange.name}: создано {total_created}, обновлено {total_updated}"


@shared_task
def exchanges_sync_all_trading_pairs() -> str:
    """Синхронизировать торговые пары для всех активных бирж."""
    exchanges = Exchange.active_objects.all()
    tasks = group(exchange_sync_trading_pairs.s(exchange.id) for exchange in exchanges)
    tasks.apply_async()
    logger.info(f"Запущена синхронизация пар для {len(exchanges)} бирж")
    return f"Запущено для {len(exchanges)} бирж"
