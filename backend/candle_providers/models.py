"""ORM модели для конфигурации провайдеров свечей."""

from django.core.exceptions import ValidationError
from django.db import models
from candle_providers.domain import AbstractCandleProvider as DomainCandleProvider
from candle_providers.domain import CandleProviderRegistry
from candle_sources.models import CandleSource
from core.utils.mixins import ActiveManagerMixin, TimeStampedMixin


class CandleProvider(TimeStampedMixin, ActiveManagerMixin, models.Model):
    """Конфигурация провайдера свечей (Plain/Division/Minus)."""

    class_name = models.CharField(
        max_length=100,
        choices=CandleProviderRegistry.get_choices,
        verbose_name="Класс провайдера свечей",
    )

    primary_source = models.ForeignKey(
        CandleSource,
        on_delete=models.CASCADE,
        related_name="primary_candle_providers",
        verbose_name="Первичный источник свечей",
    )

    secondary_source = models.ForeignKey(
        CandleSource,
        on_delete=models.CASCADE,
        related_name="secondary_candle_providers",
        null=True,
        blank=True,
        verbose_name="Вторичный источник свечей",
    )

    class Meta:
        verbose_name = "Candle Provider"
        verbose_name_plural = "Candle Providers"

    def __str__(self) -> str:
        if self.secondary_source:
            return (
                f"{self.class_name} ({self.primary_source} + {self.secondary_source})"
            )
        return f"{self.class_name} ({self.primary_source})"

    def get_class(self) -> type[DomainCandleProvider]:
        return CandleProviderRegistry.get_class(self.class_name)

    def clean(self):
        super().clean()

        if self.class_name == "PlainCandleProvider":
            if self.secondary_source:
                raise ValidationError(
                    {
                        "secondary_source": "PlainCandleProvider не должен иметь вторичный источник"
                    }
                )
            return

        if not self.secondary_source:
            raise ValidationError(
                {
                    "secondary_source": "Синтетические провайдеры требуют secondary_source"
                }
            )

        if self.primary_source.timeframe != self.secondary_source.timeframe:
            raise ValidationError(
                {
                    "secondary_source": (
                        f"Источники должны иметь одинаковый таймфрейм. "
                        f"Первичный: {self.primary_source.timeframe}, "
                        f"Вторичный: {self.secondary_source.timeframe}"
                    )
                }
            )

        if self.primary_source.trading_pair != self.secondary_source.trading_pair:
            raise ValidationError(
                {
                    "secondary_source": (
                        f"Источники должны иметь одинаковую торговую пару. "
                        f"Первичный: {self.primary_source.trading_pair}, "
                        f"Вторичный: {self.secondary_source.trading_pair}"
                    )
                }
            )

        exchange1 = self.primary_source.exchange_client.exchange
        exchange2 = self.secondary_source.exchange_client.exchange
        if exchange1 == exchange2:
            raise ValidationError(
                {
                    "secondary_source": f"Источники должны быть с разных бирж. Оба источника с {exchange1}"
                }
            )

    def instantiate(self) -> DomainCandleProvider:
        """Создает domain объект из ORM модели."""
        cls = self.get_class()
        if self.secondary_source is None:
            return cls(self.primary_source)
        return cls(self.primary_source, self.secondary_source)

    @property
    def timeframe(self) -> str:
        return self.primary_source.timeframe

    @property
    def trading_pair(self):
        return self.primary_source.trading_pair
