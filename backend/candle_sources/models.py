import asyncio
import traceback
from datetime import datetime
from typing import Generator, List, Optional

from django.db import models
from django.forms import ValidationError
from django.utils import timezone

from candle_sources.domain import CandleSource as DomainCandleSource
from candle_sources.domain import CandleSourceError as DomainCandleSourceError
from core.utils.mixins import ActiveManagerMixin, TimeStampedMixin
from core.utils.types import Timeframe
from exchange_clients.domain import AbstractExchangeClient as DomainExchangeClient
from exchange_clients.models import ExchangeClient
from exchanges.domain import Candle as DomainCandle
from exchanges.domain import Timeframe as DomainTimeframe
from exchanges.models import Candle, ExchangeCandle, TradingPair


async def exchange_client_candle_source_fetch_candles(
    source: DomainCandleSource,
    limit: Optional[int] = None,
    since: Optional[datetime] = None,
) -> List[DomainCandle]:
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
    tasks: List[asyncio.Task],
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
    errors = models.TextField(null=True, blank=True)
    last_synced = models.DateTimeField(
        verbose_name="Последняя синхронизация",
        null=True,
        blank=True,
        help_text="Дата и время последней успешной синхронизации свечей.",
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

    def instantiate(
        self, domain_exchange_client: Optional[DomainExchangeClient] = None
    ) -> DomainCandleSource:
        exchange_client = domain_exchange_client or self.exchange_client.instantiate()
        return DomainCandleSource(
            exchange_client=exchange_client,
            trading_pair=self.trading_pair.instantiate(
                exchange=self.exchange_client.exchange
            ),
            timeframe=DomainTimeframe(self.timeframe),
        )

    def __str__(self):
        return (
            f"{self.exchange_client.exchange} | {self.trading_pair} | {self.timeframe}"
        )

    def delete_all_candles(self) -> None:
        ExchangeCandle.objects.filter(
            exchange=self.exchange_client.exchange,
            timeframe=self.timeframe,
            trading_pair=self.trading_pair,
        ).delete()

    def fetch_candles(
        self,
        limit: Optional[int] = None,
        since: Optional[datetime] = None,
    ) -> List[ExchangeCandle]:
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
        domain_exchange_client = self.exchange_client.instantiate()
        domain_source = self.instantiate(domain_exchange_client=domain_exchange_client)

        try:
            tasks = []
            for step in range(total_steps):
                step_since = since + step * step_delta if since else None
                step_limit = (
                    min(exchange_candle_fetch_limit, limit - step * exchange_candle_fetch_limit)
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
            domain_candles: List[List[DomainCandle]] = asyncio.run(
                run_tasks_with_exchange_client(
                    exchange_client=domain_exchange_client,
                    tasks=tasks,
                )
            )
        except Exception as e:
            self.errors = str(e)
            CandleSourceError.objects.create(
                candle_source=self,
                message=str(e),
                type=type(e).__name__,
                traceback=traceback.format_exc(),
            )
            return []
        else:
            self.errors = None
        finally:
            self.save()

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
        limit: Optional[int] = None,
        since: Optional[datetime] = None,
    ) -> List[ExchangeCandle]:
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
        self, start: datetime, end: datetime
    ) -> models.QuerySet[ExchangeCandle]:
        return ExchangeCandle.objects.filter(
            exchange=self.exchange_client.exchange,
            timeframe=self.timeframe,
            trading_pair=self.trading_pair,
            timestamp__range=(start, end),
        ).order_by("timestamp")

    def get_candle_iterator(
        self, start: Optional[datetime] = None, end: Optional[datetime] = None
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
        for candle in candles_qs:
            yield candle

    def get_last_candles(self, count: int) -> models.QuerySet[ExchangeCandle]:
        return ExchangeCandle.objects.filter(
            exchange=self.exchange_client.exchange,
            timeframe=self.timeframe,
            trading_pair=self.trading_pair,
        ).order_by("-timestamp")[:count][::-1]


class CandleSourceError(TimeStampedMixin, models.Model):
    """Модель для хранения ошибок источника свечей."""

    candle_source = models.ForeignKey(
        CandleSource,
        on_delete=models.CASCADE,
        related_name="error_records",
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
        null=True,
        blank=True,
        verbose_name="Traceback",
    )

    class Meta:
        verbose_name = "Ошибка источника свечей"
        verbose_name_plural = "Ошибки источников свечей"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.candle_source} | {self.type} | {self.created_at}"
