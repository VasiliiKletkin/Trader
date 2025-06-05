from django.db import models

from exchanges.models import Exchange, Timeframe, TradingPair


class Candle(models.Model):
    exchange = models.ForeignKey(Exchange, on_delete=models.CASCADE)
    trading_pair = models.ForeignKey(
        TradingPair,
        on_delete=models.CASCADE,
    )
    timeframe = models.CharField(
        max_length=3,
        choices=Timeframe.choices,
        default=Timeframe.ONE_MINUTE,
    )
    timestamp = models.DateTimeField(
        verbose_name="Временная метка",
    )
    high = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        verbose_name="Максимальная цена за период свечи",
    )
    low = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        verbose_name="Минимальная цена за период свечи",
    )
    open = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        verbose_name="Цена открытия свечи",
    )
    close = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        verbose_name="Цена закрытия свечи",
    )
    volume = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        verbose_name="Объём за период свечи",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["exchange", "timestamp"], name="unique_exchange_timestamp"
            )
        ]

    def __str__(self):
        return f"date:{self.timestamp}, open:{self.open}, close:{self.close}"
