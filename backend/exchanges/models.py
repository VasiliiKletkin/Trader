from datetime import datetime, timedelta
from typing import List, Optional
from django.utils.timezone import make_naive

import requests
from core.utils.mixins import ActiveManagerMixin, TimeStampedMixin
from django.db import models
from django.urls import reverse
from django.utils import timezone
from exchanges.domain.exchanges.base import AbstractExchange, ExchangeRegistry
from loguru import logger


class ProxyProtocol(models.TextChoices):
    SOCKS5 = "socks5", "Socks5"
    SOCKS4 = "socks4", "Socks4"


class Proxy(ActiveManagerMixin, TimeStampedMixin, models.Model):
    protocol = models.CharField(
        max_length=10,
        choices=ProxyProtocol.choices,
        default=ProxyProtocol.SOCKS5,
    )
    address = models.CharField(max_length=100, unique=True)
    port = models.IntegerField()
    username = models.CharField(max_length=100)
    password = models.CharField(max_length=100)

    errors = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"{self.protocol}://{self.username}:{self.password}@{self.address}:{self.port}"

    @property
    def is_ready(self):
        return self.is_active and not self.errors

    def check_obj(self):
        try:
            proxies = {"http": str(self)}
            response = requests.get(
                "http://www.httpbin.org/ip",
                proxies=proxies,
            )
            resp_data = response.json()

            if resp_data["origin"] != self.address:
                raise Exception(
                    f'Ip address{self.address} is not equal from http://www.httpbin.org/ip {resp_data["origin"]}'
                )

        except Exception as error:
            self.error = str(error)
        else:
            self.error = None
        finally:
            self.save()

    def get_proxy_dict(self):
        return {
            "proxy_type": self.protocol,
            "addr": self.address,
            "port": self.port,
            "username": self.username,
            "password": self.password,
            "rdns": True,
        }


class TradingPair(models.Model):
    name = models.CharField(max_length=15)

    class Meta:
        verbose_name = "Торговая пара"
        verbose_name_plural = "Торговые пары"

    def __str__(self):
        return self.name


class Timeframe(models.TextChoices):
    ONE_MINUTE = "1m", "1 Minute"
    FIVE_MINUTES = "5m", "5 Minutes"
    FIFTEEN_MINUTES = "15m", "15 Minutes"
    ONE_HOUR = "1h", "1 Hour"
    FOUR_HOURS = "4h", "4 Hours"
    ONE_DAY = "1d", "1 Day"
    ONE_WEEK = "1w", "1 Week"

    def as_timedelta(self) -> timedelta:
        return {
            self.ONE_MINUTE: timedelta(minutes=1),
            self.FIVE_MINUTES: timedelta(minutes=5),
            self.FIFTEEN_MINUTES: timedelta(minutes=15),
            self.ONE_HOUR: timedelta(hours=1),
            self.FOUR_HOURS: timedelta(hours=4),
            self.ONE_DAY: timedelta(days=1),
            self.ONE_WEEK: timedelta(weeks=1),
        }[self]


class Exchange(ActiveManagerMixin, TimeStampedMixin, models.Model):
    name = models.CharField(max_length=20)
    class_name = models.CharField(
        max_length=30,
        choices=ExchangeRegistry.get_choices,
    )
    api_key = models.CharField(max_length=200)
    api_secret = models.CharField(max_length=200)
    demo = models.BooleanField(default=True)
    proxy = models.ForeignKey(Proxy, models.CASCADE, null=True, blank=True)

    class Meta:
        verbose_name = "Биржа"
        verbose_name_plural = "Биржи"
        constraints = [
            models.UniqueConstraint(
                fields=["api_key", "api_secret"],
                name="unique_api_key_api_secret",
            )
        ]

    def get_exchange_class(self) -> "AbstractExchange":
        return ExchangeRegistry.get_class(self.class_name)

    def instantiate(self, **kwargs) -> "AbstractExchange":
        cls = self.get_exchange_class()
        return cls(
            api_key=self.api_key, api_secret=self.api_secret, demo=self.demo, **kwargs
        )

    def __str__(self):
        return self.name


class Candle(models.Model):
    candle_source = models.ForeignKey(
        "CandleSource",
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
        verbose_name = "Свеча"
        verbose_name_plural = "Свечи"
        constraints = [
            models.UniqueConstraint(
                fields=["candle_source", "timestamp"],
                name="unique_candle_source_timestamp",
            )
        ]

    def __str__(self):
        return f"date:{self.timestamp}, open:{self.open}, close:{self.close}"

    def timestamp_unix(self) -> int:
        """
        Возвращает временную метку в формате UNIX (в млс).
        """
        naive_ts = make_naive(self.timestamp)
        return int(naive_ts.timestamp() * 1000)


class CandleSource(ActiveManagerMixin, TimeStampedMixin, models.Model):
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

    class Meta:
        verbose_name = "Источник свечей"
        verbose_name_plural = "Источники свечей"
        constraints = [
            models.UniqueConstraint(
                fields=["exchange", "trading_pair", "timeframe"],
                name="unique_exchange_pair_timeframe",
            )
        ]

    def __str__(self):
        return f"{self.exchange.name} | {self.trading_pair.name} | {self.timeframe}"

    def get_absolute_url(self):
        return reverse("candle_source_detail", kwargs={"pk": self.pk})

    def get_candles(
        self,
        limit: Optional[int] = None,
        since: Optional[datetime] = None,
    ) -> List[Candle]:
        trading_pair = self.trading_pair.name
        tf_enum = Timeframe(self.timeframe)

        logger.info(
            f"📡 Получение свечей: {self.exchange.name} | {trading_pair} | {tf_enum.value}"
        )
        if since:
            logger.debug(f"🕓 С начала: {since.isoformat()}")
        if limit:
            logger.debug(f"🔢 Лимит: {limit}")
        exchange_instance = self.exchange.instantiate()
        try:
            candles_raw = exchange_instance.get_market_candles(
                trading_pair=trading_pair,
                timeframe=tf_enum.value,
                since=since,
                limit=limit,
            )
        except Exception as e:
            logger.error(f"❌ Ошибка получения свечей: {e}")
            return []

        logger.success(f"✅ Получено {len(candles_raw)} свечей")

        candles = [
            Candle(
                candle_source=self,
                timestamp=timezone.make_aware(c.timestamp),
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
                volume=c.volume,
            )
            for c in candles_raw
        ]

        return candles

    def save_candles(
        self,
        limit: Optional[int] = None,
        since: Optional[datetime] = None,
    ) -> List[Candle]:
        new_candles = self.get_candles(limit=limit, since=since)
        candles = Candle.objects.bulk_create(
            new_candles,
            update_conflicts=True,
            update_fields=["open", "high", "low", "close", "volume"],
            unique_fields=["candle_source", "timestamp"],
        )
        return candles
