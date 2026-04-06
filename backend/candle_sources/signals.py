from django.db.models.signals import post_delete
from django.dispatch import receiver

from candle_sources.models import CandleSource
from candle_sources.tasks import delete_candles


@receiver(post_delete, sender=CandleSource)
def delete_candles_on_source_delete(sender, instance, **kwargs):
    """Отправляет задачу на удаление свечей при удалении источника."""
    delete_candles.delay(
        exchange_id=instance.exchange_id,
        trading_pair_id=instance.trading_pair_id,
        timeframe=instance.timeframe,
    )
