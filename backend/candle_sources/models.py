import asyncio
import traceback
from collections.abc import Iterator
from datetime import datetime

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone

from candle_sources.domain import CandleSource as DomainCandleSource
from core.utils.mixins import ActiveManagerMixin, BaseErrorMixin, TimeStampedMixin
from exchange_clients.domain import AbstractExchangeClient as DomainExchangeClient
from exchange_clients.models import ExchangeClient
from exchanges.domain import Candle as DomainCandle
from exchanges.domain import Timeframe as DomainTimeframe
from exchanges.models import ExchangeCandle, ExchangeTradingPair, TradingPair
from exchanges.schemas import Timeframe


class CandleSourceMode(models.TextChoices):
    REST = "rest", "REST"
    WEBSOCKET = "ws", "WebSocket"


class CandleSource(ActiveManagerMixin, TimeStampedMixin, models.Model):
    exchange_client = models.ForeignKey(
        ExchangeClient,
        on_delete=models.CASCADE,
        related_name="candle_sources",
        verbose_name="Клиент биржи",
    )
    trading_pair = models.ForeignKey(
        TradingPair,
        on_delete=models.CASCADE,
        verbose_name="Торговая пара",
    )
    timeframe = models.CharField(
        max_length=3,
        choices=Timeframe.choices,
        default=Timeframe.ONE_MINUTE,
        verbose_name="Таймфрейм",
    )
    mode = models.CharField(
        max_length=4,
        choices=CandleSourceMode,
        default=CandleSourceMode.REST,
        verbose_name="Режим получения данных",
    )
    last_synced = models.DateTimeField(  # type: ignore[misc]
        verbose_name="Последняя синхронизация",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Источник свечей"
        verbose_name_plural = "Источники свечей"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "exchange_client",
                    "trading_pair",
                    "timeframe",
                ],
                name="unique_candle_source",
            )
        ]

    def __str__(self):
        return (
            f"{self.exchange_client.exchange} | {self.trading_pair} | {self.timeframe}"
        )

    def get_absolute_url(self):
        return reverse("candle_source_detail", kwargs={"pk": self.pk})

    def clean(self) -> None:
        super().clean()
        if not ExchangeTradingPair.objects.filter(
            exchange=self.exchange_client.exchange,
            trading_pair=self.trading_pair,
        ).exists():
            raise ValidationError(
                f"Торговая пара «{self.trading_pair}» отсутствует "
                f"на бирже «{self.exchange_client.exchange}»."
            )

        duplicate = CandleSource.objects.filter(
            exchange_client__exchange=self.exchange_client.exchange,
            trading_pair=self.trading_pair,
            timeframe=self.timeframe,
        ).exclude(pk=self.pk)
        if duplicate.exists():
            raise ValidationError(
                f"Источник свечей для «{self.trading_pair}» "
                f"({self.timeframe}) на бирже «{self.exchange_client.exchange}» "
                f"уже существует."
            )

    @property
    def is_ready(self) -> bool:
        return all(
            [
                self.is_active,
                self.exchange_client.is_ready,
            ]
        )

    def activate(self):
        self.is_active = True
        self.save(update_fields=["is_active"])

    def deactivate(self):
        self.is_active = False
        self.save(update_fields=["is_active"])

    def instantiate(
        self, domain_exchange_client: DomainExchangeClient | None = None
    ) -> DomainCandleSource:
        exchange_client = domain_exchange_client or self.exchange_client.instantiate()
        return DomainCandleSource(
            exchange_client=exchange_client,
            trading_pair=self.trading_pair.instantiate(
                exchange=self.exchange_client.exchange
            ),
            timeframe=DomainTimeframe(self.timeframe),
            source_id=self.pk,
        )

    @property
    def candles(self) -> models.QuerySet[ExchangeCandle]:
        return ExchangeCandle.objects.filter(
            exchange=self.exchange_client.exchange,
            timeframe=self.timeframe,
            trading_pair=self.trading_pair,
        )

    def delete_all_candles(self) -> None:
        self.candles.all().delete()

    def clear_all_data(self) -> None:
        self.candles.all().delete()
        self.errors.all().delete()
        self.last_synced = None
        self.save(update_fields=["last_synced"])

    def fetch_candles(
        self,
        limit: int | None = None,
        since: datetime | None = None,
    ) -> list[ExchangeCandle]:
        if since and timezone.is_naive(since):
            since = timezone.make_aware(since)
        if since and since > timezone.now():
            raise ValueError("Since не может быть в будущем.")

        try:
            domain_source = self.instantiate(
                domain_exchange_client=self.exchange_client.get_rpc_client(),
            )
            domain_candles: list[DomainCandle] = asyncio.run(
                domain_source.fetch_candles_paginated(limit=limit, since=since)
            )
        except Exception as e:
            self.errors.create(
                message=str(e),
                type=type(e).__name__,
                traceback=traceback.format_exc(),
            )
            return []

        if domain_source.errors:
            CandleSourceError.objects.bulk_create(
                [
                    CandleSourceError(
                        candle_source=self,
                        message=err.message,
                        type=err.type,
                        traceback=err.traceback or "",
                    )
                    for err in domain_source.errors
                ]
            )

        return [
            ExchangeCandle(
                exchange=self.exchange_client.exchange,
                timeframe=self.timeframe,
                trading_pair=self.trading_pair,
                timestamp=c.timestamp,
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
                volume=c.volume,
            )
            for c in domain_candles
        ]

    def sync_candles(
        self,
        limit: int | None = None,
        since: datetime | None = None,
    ) -> list[ExchangeCandle]:
        candles = self.fetch_candles(limit=limit, since=since)
        if not candles:
            return []

        created_candles = ExchangeCandle.objects.bulk_create(
            candles,
            batch_size=settings.BULK_BATCH_SIZE,
            update_conflicts=True,
            update_fields=["open", "high", "low", "close", "volume"],
            unique_fields=["exchange", "timeframe", "trading_pair", "timestamp"],
        )

        self.last_synced = timezone.now()
        self.save(update_fields=["last_synced"])

        return created_candles

    def get_last_candle(self) -> ExchangeCandle | None:
        candles = self.get_last_candles(count=1)
        return candles[0] if candles else None

    def get_candles(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> models.QuerySet[ExchangeCandle]:
        candles = self.candles
        if start:
            candles = candles.filter(timestamp__gte=start)
        if end:
            candles = candles.filter(timestamp__lte=end)
        return candles.order_by("timestamp")

    def get_candle_iterator(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> Iterator[ExchangeCandle]:
        return self.get_candles(start=start, end=end).iterator()

    def get_last_candles(self, count: int = 1000) -> list[ExchangeCandle]:
        candles = list(self.candles.order_by("-timestamp")[:count])
        candles.reverse()
        return candles


class CandleSourceError(BaseErrorMixin, TimeStampedMixin, models.Model):
    """Модель для хранения ошибок источника свечей."""

    candle_source = models.ForeignKey(
        CandleSource,
        on_delete=models.CASCADE,
        related_name="errors",
        verbose_name="Источник свечей",
    )

    class Meta:
        verbose_name = "Ошибка источника свечей"
        verbose_name_plural = "Ошибки источников свечей"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return super().__str__()
