from django.db import models

from exchanges.models import CandleSource


class Candle(models.Model):
    # candle_source = models.ForeignKey(
    #     CandleSource,
    #     on_delete=models.CASCADE,
    # )
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
        pass
        # constraints = [
        #     models.UniqueConstraint(
        #         fields=["exchange", "timestamp"], name="unique_exchange_timestamp"
        #     )
        # ]

    def __str__(self):
        return f"date:{self.timestamp}, open:{self.open}, close:{self.close}"
