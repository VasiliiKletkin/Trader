import asyncio
from datetime import datetime
from typing import Generator, List, Optional

from django.db import models
from django.forms import ValidationError
from django.utils import timezone

from candle_sources.domain import CandleSource as DomainCandleSource
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
        if since and since > now:
            raise ValueError("Since не может быть в будущем.")

        default_count = 999
        step_delta = tf.timedelta() * default_count
        total_steps = 1

        if since:
            total_steps = ((now - since) // step_delta) + 1
        if limit:
            total_steps = min(total_steps, (limit // default_count) + 1)

        try:
            domain_exchange_client = self.exchange_client.instantiate()

            tasks = []
            for step in range(total_steps):
                step_since = since + step * step_delta if since else None
                step_limit = (
                    min(default_count, limit - step * default_count)
                    if limit
                    else default_count
                )
                tasks.append(
                    exchange_client_candle_source_fetch_candles(
                        source=self.instantiate(
                            domain_exchange_client=domain_exchange_client
                        ),
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
            return []
        else:
            self.errors = None
        finally:
            self.save()

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

        return ExchangeCandle.objects.bulk_create(
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

    def get_last_candles(self, count: int) -> models.QuerySet[ExchangeCandle]:
        return ExchangeCandle.objects.filter(
            exchange=self.exchange_client.exchange,
            timeframe=self.timeframe,
            trading_pair=self.trading_pair,
        ).order_by("-timestamp")[:count][::-1]

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
