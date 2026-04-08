from django.db.models.signals import post_delete
from django.dispatch import receiver

from candle_sources.models import CandleSource
from exchanges.models import ExchangeCandle


@receiver(post_delete, sender=CandleSource)
def delete_candles_on_source_delete(sender, instance, **kwargs):
    """Удаляет свечи при удалении источника."""
    ExchangeCandle.objects.filter(
        exchange_id=instance.exchange_id,
        trading_pair_id=instance.trading_pair_id,
        timeframe=instance.timeframe,
    ).delete()
