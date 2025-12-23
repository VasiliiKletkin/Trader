from datetime import datetime
from typing import Generator, List, Optional
from exchanges.models import ExchangeCandle, Candle

from candle_sources.domain import AbstractCandleSource as DomainCandleSource
from candle_sources.domain import CandleSourceRegistry
from django.db import models
from exchange_clients.models import ExchangeClientCandleSource
from django.forms import ValidationError
from core.utils.mixins import ActiveManagerMixin


class CandleSource(ActiveManagerMixin, models.Model):
    class_name = models.CharField(
        max_length=100,
        choices=CandleSourceRegistry.get_choices,
        verbose_name="Класс источника свечей",
    )

    exchange_client_candle_sources = models.ManyToManyField(ExchangeClientCandleSource)

    class Meta:
        verbose_name = "Источник свечей"
        verbose_name_plural = "Источники свечей"

    def __str__(self):
        candle_sources = self.exchange_client_candle_sources.order_by("id")
        return ", ".join([f"{cs}" for cs in candle_sources]) + f" ({self.class_name})"

    def get_class(self) -> type[DomainCandleSource]:
        return CandleSourceRegistry.get_class(self.class_name)

    def clean(self):
        # eccs_count = self.exchange_client_candle_sources.count()
        # if not 1 <= eccs_count <= 2:
        #     raise ValidationError(
        #         "Должен быть выбран хотя бы 1 и не более 2 источников свечей."
        #     )
        # trading_pair_count = (
        #     self.exchange_client_candle_sources.values("trading_pair_id")
        #     .distinct()
        #     .count()
        # )
        # if not trading_pair_count == 1:
        #     raise ValidationError(
        #         "Все источники свечей должны иметь одинаковую торговую пару."
        #     )
        # timeframe_count = (
        #     self.exchange_client_candle_sources.values("timeframe").distinct().count()
        # )
        # if not timeframe_count == 1:
        #     raise ValidationError(
        #         "Все источники свечей должны иметь одинаковый таймфрейм."
        #     )
        # exchanges_count = (
        #     self.exchange_client_candle_sources.values("exchange_client__exchange_id")
        #     .distinct()
        #     .count()
        # )
        # if not exchanges_count == eccs_count:
        #     raise ValidationError("Все источники свечей должны иметь разные биржи.")
        return super().clean()

    def instantiate(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> DomainCandleSource:
        """
        Создаёт domain объект CandleSource.

        Оптимизация: Использует prefetch кеш если доступен, что позволяет
        избежать дополнительных запросов к БД при использовании
        get_optimized_trader_queryset().
        """
        cls = self.get_class()

        if hasattr(self, '_prefetched_objects_cache') and \
           'exchange_client_candle_sources' in self._prefetched_objects_cache:
            candle_sources = sorted(
                self.exchange_client_candle_sources.all(),
                key=lambda x: x.id
            )
        else:
            candle_sources = self.exchange_client_candle_sources.order_by("id")

        def get_candle_iterator(eccs: ExchangeClientCandleSource):
            filtered_candles = eccs.candles.all()
            if start_date:
                filtered_candles = filtered_candles.filter(timestamp__gte=start_date)
            if end_date:
                filtered_candles = filtered_candles.filter(timestamp__lt=end_date)
            return (
                candle.instantiate()
                for candle in filtered_candles.order_by("timestamp").iterator()
            )

        candle_iterators = (get_candle_iterator(eccs) for eccs in candle_sources)
        return cls(*candle_iterators)

    def get_candle(self, *candles: ExchangeCandle) -> Candle:
        """
        Получает одну или две свечи (для Plain/Division источников) и возвращает агрегированную свечу.
        """
        candle_source = self.instantiate()
        domain_candles = [candle.instantiate() for candle in candles]
        result = candle_source.get_candle(*domain_candles)
        return Candle(
            timestamp=result.timestamp,
            high=result.high,
            low=result.low,
            open=result.open,
            close=result.close,
            volume=result.volume,
        )

    def get_candle_iterator(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Generator[Candle, None, None]:
        """
        Генератор свечей для бэктеста.
        Возвращает ORM Candle объекты с атрибутом _source_candles.
        domain_candle всегда SyntheticCandle с обязательным source_candles.
        """
        candle_source = self.instantiate(start_date=start_date, end_date=end_date)
        return (
            Candle(
                timestamp=candle.timestamp,
                high=candle.high,
                low=candle.low,
                open=candle.open,
                close=candle.close,
                volume=candle.volume,
            )
            for candle in candle_source.get_candle_iterator()
        )

    def get_candles(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List[Candle]:
        """
        Получает список свечей за период.
        Возвращает ORM Candle объекты с атрибутом _source_candles.
        domain_candle всегда SyntheticCandle с обязательным source_candles.
        """
        candle_source = self.instantiate(start_date=start_date, end_date=end_date)
        return [
            Candle(
                timestamp=candle.timestamp,
                high=candle.high,
                low=candle.low,
                open=candle.open,
                close=candle.close,
                volume=candle.volume,
            )
            for candle in candle_source.get_candles()
        ]

    def get_last_candles(self, count: Optional[int] = 1000) -> List[Candle]:
        candle_source = self.instantiate()
        return [
            Candle(
                timestamp=candle.timestamp,
                high=candle.high,
                low=candle.low,
                open=candle.open,
                close=candle.close,
                volume=candle.volume,
            )
            for candle in candle_source.get_last_candles(count=count)
        ]
