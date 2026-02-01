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

    first_source = models.ForeignKey(
        CandleSource,
        on_delete=models.CASCADE,
        related_name="first_candle_providers",
        verbose_name="Первичный источник свечей",
    )

    second_source = models.ForeignKey(
        CandleSource,
        on_delete=models.CASCADE,
        related_name="second_candle_providers",
        null=True,
        blank=True,
        verbose_name="Вторичный источник свечей",
    )

    class Meta:
        verbose_name = "Candle Provider"
        verbose_name_plural = "Candle Providers"

    def __str__(self) -> str:
        if self.second_source:
            return (
                f"{self.class_name} ({self.first_source} + {self.second_source})"
            )
        return f"{self.class_name} ({self.first_source})"

    def get_class(self) -> type[DomainCandleProvider]:
        return CandleProviderRegistry.get_class(self.class_name)

    def clean(self):
        super().clean()

        if self.class_name == "PlainCandleProvider":
            if self.second_source:
                raise ValidationError(
                    {
                        "second_source": "PlainCandleProvider не должен иметь вторичный источник"
                    }
                )
            return

        if not self.second_source:
            raise ValidationError(
                {
                    "second_source": "Синтетические провайдеры требуют second_source"
                }
            )

        if self.first_source.timeframe != self.second_source.timeframe:
            raise ValidationError(
                {
                    "second_source": (
                        f"Источники должны иметь одинаковый таймфрейм. "
                        f"Первичный: {self.first_source.timeframe}, "
                        f"Вторичный: {self.second_source.timeframe}"
                    )
                }
            )

        if self.first_source.trading_pair != self.second_source.trading_pair:
            raise ValidationError(
                {
                    "second_source": (
                        f"Источники должны иметь одинаковую торговую пару. "
                        f"Первичный: {self.first_source.trading_pair}, "
                        f"Вторичный: {self.second_source.trading_pair}"
                    )
                }
            )

        exchange1 = self.first_source.exchange_client.exchange
        exchange2 = self.second_source.exchange_client.exchange
        if exchange1 == exchange2:
            raise ValidationError(
                {
                    "second_source": f"Источники должны быть с разных бирж. Оба источника с {exchange1}"
                }
            )

    def instantiate(self) -> DomainCandleProvider:
        """Создает domain объект из ORM модели."""
        cls = self.get_class()
        if self.second_source is None:
            return cls(self.first_source)
        return cls(self.first_source, self.second_source)

    @property
    def timeframe(self) -> str:
        return self.first_source.timeframe

    @property
    def trading_pair(self):
        return self.first_source.trading_pair
