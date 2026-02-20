import asyncio
import traceback
from collections.abc import Generator
from datetime import datetime

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from candle_sources.domain import CandleSource as DomainCandleSource
from candle_sources.domain import CandleSourceError as DomainCandleSourceError
from core.utils.mixins import ActiveManagerMixin, TimeStampedMixin
from exchange_clients.domain import AbstractExchangeClient as DomainExchangeClient
from exchange_clients.models import ExchangeClient
from exchanges.domain import Candle as DomainCandle
from exchanges.domain import Timeframe as DomainTimeframe
from exchanges.models import ExchangeCandle, TradingPair
from exchanges.schemas import Timeframe


async def exchange_client_candle_source_fetch_candles(
    source: DomainCandleSource,
    limit: int | None = None,
    since: datetime | None = None,
) -> list[DomainCandle]:
    try:
        candles = await source.fetch_candles(limit=limit, since=since)
        return candles
    except Exception as e:
        source.errors.append(
            DomainCandleSourceError(
                message=str(e),
                type=type(e).__name__,
                traceback=traceback.format_exc(),
            )
        )
        return []


async def run_tasks_with_exchange_client(
    exchange_client: DomainExchangeClient,
    tasks: list[asyncio.Task],  # type: ignore[arg-type]
):
    async with exchange_client:
        return await asyncio.gather(*tasks)


class CandleSource(ActiveManagerMixin, TimeStampedMixin, models.Model):
    exchange_client = models.ForeignKey(
        ExchangeClient,
        on_delete=models.CASCADE,
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
        tf = Timeframe(self.timeframe)

        now = timezone.now()
        if since and timezone.is_naive(since):
            since = timezone.make_aware(since)
        if since and since > now:
            raise ValueError("Since не может быть в будущем.")

        exchange_candle_fetch_limit = self.exchange_client.exchange.candle_fetch_limit
        step_delta = tf.timedelta() * exchange_candle_fetch_limit
        total_steps = 1

        if since:
            total_steps = ((now - since) // step_delta) + 1
        if limit:
            total_steps = min(total_steps, (limit // exchange_candle_fetch_limit) + 1)

        try:
            domain_exchange_client = self.exchange_client.instantiate()
            domain_source = self.instantiate(
                domain_exchange_client=domain_exchange_client
            )
            tasks = []
            for step in range(total_steps):
                step_since = since + step * step_delta if since else None
                step_limit = (
                    min(
                        exchange_candle_fetch_limit,
                        limit - step * exchange_candle_fetch_limit,
                    )
                    if limit
                    else exchange_candle_fetch_limit
                )
                tasks.append(
                    exchange_client_candle_source_fetch_candles(
                        source=domain_source,
                        limit=step_limit,
                        since=step_since,
                    )
                )
            domain_candles: list[list[DomainCandle]] = asyncio.run(
                run_tasks_with_exchange_client(
                    exchange_client=domain_exchange_client,
                    tasks=tasks,  # type: ignore[arg-type]
                )
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
                        message=error.message,
                        type=error.type,
                        traceback=error.traceback,
                    )
                    for error in domain_source.errors
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
            for sub_candles in domain_candles
            for c in sub_candles
        ]

    def sync_candles(
        self,
        limit: int | None = None,
        since: datetime | None = None,
    ) -> list[ExchangeCandle]:
        candles = self.fetch_candles(limit=limit, since=since)
        unique_candles = {}
        for candle in candles:
            key = (
                candle.exchange.pk,
                candle.timeframe,
                candle.trading_pair.pk,
                candle.timestamp,
            )
            unique_candles[key] = candle

        candles_to_create = list(unique_candles.values())

        created_candles = ExchangeCandle.objects.bulk_create(
            candles_to_create,
            batch_size=settings.BULK_BATCH_SIZE,
            update_conflicts=True,
            update_fields=[
                "open",
                "high",
                "low",
                "close",
                "volume",
            ],
            unique_fields=[
                "exchange",
                "timeframe",
                "trading_pair",
                "timestamp",
            ],
        )

        if created_candles:
            self.last_synced = timezone.now()
            self.save(update_fields=["last_synced"])

        return created_candles

    def candles_count(self) -> int:
        return ExchangeCandle.objects.filter(
            exchange=self.exchange_client.exchange,
            timeframe=self.timeframe,
            trading_pair=self.trading_pair,
        ).count()

    def get_candles(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> models.QuerySet[ExchangeCandle]:
        queryset = ExchangeCandle.objects.filter(
            exchange=self.exchange_client.exchange,
            timeframe=self.timeframe,
            trading_pair=self.trading_pair,
        )
        if start:
            queryset = queryset.filter(timestamp__gte=start)
        if end:
            queryset = queryset.filter(timestamp__lte=end)
        return queryset.order_by("timestamp")

    def get_candle_iterator(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> Generator[ExchangeCandle, None, None]:
        queryset = ExchangeCandle.objects.filter(
            exchange=self.exchange_client.exchange,
            timeframe=self.timeframe,
            trading_pair=self.trading_pair,
        )
        if start:
            queryset = queryset.filter(timestamp__gte=start)
        if end:
            queryset = queryset.filter(timestamp__lte=end)

        candles_qs = queryset.order_by("timestamp").iterator()
        yield from candles_qs

    def get_last_candles(self, count: int = 1000) -> list[ExchangeCandle]:
        candles = list(
            ExchangeCandle.objects.filter(
                exchange=self.exchange_client.exchange,
                timeframe=self.timeframe,
                trading_pair=self.trading_pair,
            ).order_by("-timestamp")[:count]
        )
        candles.reverse()
        return candles


class CandleSourceError(TimeStampedMixin, models.Model):
    """Модель для хранения ошибок источника свечей."""

    candle_source = models.ForeignKey(
        CandleSource,
        on_delete=models.CASCADE,
        related_name="errors",
        verbose_name="Источник свечей",
    )
    message = models.TextField(
        verbose_name="Сообщение об ошибке",
    )
    type = models.CharField(
        max_length=100,
        verbose_name="Тип ошибки",
    )
    traceback = models.TextField(
        blank=True,
        default="",
        verbose_name="Traceback",
    )

    class Meta:
        verbose_name = "Ошибка источника свечей"
        verbose_name_plural = "Ошибки источников свечей"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.candle_source} | {self.type} | {self.created_at}"
