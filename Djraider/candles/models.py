from django.db import models

from exchanges.models import Exchange, Timeframe, TradingPair


class CandleSource(models.Model):
    is_active = models.BooleanField(default=True)
    exchange = models.ForeignKey(
        Exchange,
        on_delete=models.CASCADE,
        related_name="candle_sources",
    )
    trading_pair = models.ForeignKey(
        TradingPair,
        on_delete=models.CASCADE,
        related_name="candle_sources",
    )
    timeframe = models.CharField(
        max_length=3,
        choices=Timeframe.choices,
        default=Timeframe.ONE_MINUTE,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Candle Source"
        verbose_name_plural = "Candle Sources"
        constraints = [
            models.UniqueConstraint(
                fields=["exchange", "trading_pair", "timeframe"],
                name="unique_exchange_pair_timeframe",
            )
        ]

    def __str__(self):
        return f"{self.exchange.name} | {self.trading_pair.name} | {self.timeframe}"


class Candle(models.Model):
    candle_source = models.ForeignKey(
        CandleSource,
        on_delete=models.CASCADE,
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
