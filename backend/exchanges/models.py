import asyncio
from decimal import Decimal

from django.db import models
from django.utils import timezone

from core.utils.mixins import ActiveManagerMixin, TimeStampedMixin
from exchanges.domain import Candle as DomainCandle
from exchanges.domain import Exchange as DomainExchange
from exchanges.domain import ExchangeCandle as DomainExchangeCandle
from exchanges.domain import ExchangeRegistry
from exchanges.domain import TradingPair as DomainTradingPair
from exchanges.schemas import MarketType, Timeframe


class Exchange(ActiveManagerMixin, TimeStampedMixin, models.Model):
    name = models.CharField(
        max_length=20,
        unique=True,
        verbose_name="Название",
    )
    class_name = models.CharField(
        max_length=30,
        choices=ExchangeRegistry.get_choices,
        unique=True,
        verbose_name="Класс биржи",
    )
    max_candles_per_request = models.PositiveIntegerField(
        default=999,
        verbose_name="Лимит загрузки свечей",
        help_text="Максимальное количество свечей за один запрос к API биржи",
    )
    timeout = models.PositiveIntegerField(
        default=30000,
        verbose_name="Таймаут (мс)",
        help_text="Максимальное время ожидания ответа от API биржи",
    )
    rate_limit = models.PositiveIntegerField(
        default=500,
        verbose_name="Rate limit (мс)",
        help_text="Минимальный интервал между запросами к API биржи",
    )

    class Meta:
        verbose_name = "Биржа"
        verbose_name_plural = "Биржи"

    def __str__(self):
        return self.name

    def get_class(self):
        return ExchangeRegistry.get_class(self.class_name)

    def instantiate(self) -> DomainExchange:
        cls = self.get_class()
        return cls(
            name=self.name,
            max_candles_per_request=self.max_candles_per_request,
            timeout=self.timeout,
            rate_limit=self.rate_limit,
        )

    def fetch_trading_pairs(self) -> list[DomainTradingPair]:
        """Получить торговые пары с биржи через ccxt."""
        domain_exchange = self.instantiate()
        return asyncio.run(domain_exchange.load_markets())

    def sync_trading_pairs(self) -> tuple[int, int]:
        """Синхронизировать торговые пары с биржи. Возвращает (created, updated)."""
        domain_pairs = self.fetch_trading_pairs()

        created_count = 0
        updated_count = 0
        for tp in domain_pairs:
            trading_pair, _ = TradingPair.objects.get_or_create(
                name=tp.name,
                type=tp.type,
                defaults={
                    "symbol": tp.symbol,
                    "min_amount": tp.min_amount,
                    "max_amount": tp.max_amount,
                    "fee_percent": tp.fee_percent,
                },
            )
            _, created = ExchangeTradingPair.objects.update_or_create(
                exchange=self,
                trading_pair=trading_pair,
                defaults={
                    "symbol": tp.symbol,
                    "min_amount": tp.min_amount,
                    "max_amount": tp.max_amount,
                    "fee_percent": tp.fee_percent,
                    "taker_fee": tp.taker_fee,
                    "maker_fee": tp.maker_fee,
                    "max_leverage": tp.max_leverage,
                },
            )
            if created:
                created_count += 1
            else:
                updated_count += 1
        return created_count, updated_count


class TradingPair(TimeStampedMixin, models.Model):
    name = models.CharField(
        max_length=50,
        verbose_name="Название",
        default="BTC/USDT",
    )
    symbol = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Символ",
        default="BTC/USDT:USDT",
    )
    type = models.CharField(
        max_length=10,
        choices=MarketType.choices,
        default=MarketType.FUTURES,
        verbose_name="Тип рынка",
    )
    min_amount = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        default=Decimal("0.001"),
        verbose_name="Минимальное количество",
    )
    max_amount = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        default=Decimal("1000000"),
        verbose_name="Максимальное количество",
    )
    fee_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.1"),
        verbose_name="Комиссия (%)",
    )

    class Meta:
        verbose_name = "Торговая пара"
        verbose_name_plural = "Торговые пары"
        constraints = [
            models.UniqueConstraint(
                fields=["name", "type"],
                name="unique_trading_pair",
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.get_type_display()})"

    def instantiate(self, exchange: Exchange | None = None) -> DomainTradingPair:
        if exchange:
            exchange_trading_pair = ExchangeTradingPair.objects.filter(
                exchange=exchange, trading_pair=self
            ).first()
            if exchange_trading_pair:
                return exchange_trading_pair.instantiate()
        return DomainTradingPair(
            name=self.name,
            symbol=self.symbol,
            type=self.type,
            min_amount=self.min_amount,
            max_amount=self.max_amount,
            fee_percent=self.fee_percent,
        )


class ExchangeTradingPair(TimeStampedMixin, models.Model):
    exchange = models.ForeignKey(
        Exchange,
        on_delete=models.CASCADE,
        related_name="trading_pairs",
        verbose_name="Биржа",
    )
    trading_pair = models.ForeignKey(
        TradingPair,
        on_delete=models.CASCADE,
        verbose_name="Торговая пара",
    )
    symbol = models.CharField(
        max_length=50,
        verbose_name="Символ",
        default="BTC/USDT:USDT",
    )
    min_amount = models.DecimalField(  # type: ignore[misc]
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Минимальное количество",
    )
    max_amount = models.DecimalField(  # type: ignore[misc]
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Максимальное количество",
    )
    fee_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.1"),
        verbose_name="Комиссия (%)",
    )
    taker_fee = models.DecimalField(
        max_digits=6,
        decimal_places=5,
        default=Decimal("0.001"),
        verbose_name="Комиссия Taker",
        help_text="Коэффициент, например 0.001 = 0.1%",
    )
    maker_fee = models.DecimalField(
        max_digits=6,
        decimal_places=5,
        default=Decimal("0.001"),
        verbose_name="Комиссия Maker",
        help_text="Коэффициент, например 0.001 = 0.1%",
    )
    max_leverage = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        default=Decimal("1"),
        verbose_name="Максимальное плечо",
        help_text="Например 125 для 125x",
    )

    class Meta:
        verbose_name = "Торговая пара биржи"
        verbose_name_plural = "Торговые пары бирж"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "exchange",
                    "trading_pair",
                ],
                name="unique_exchange_trading_pair",
            )
        ]

    def __str__(self):
        return f"{self.exchange.name} - {self.trading_pair.name}"

    def instantiate(self, exchange: Exchange | None = None) -> DomainTradingPair:
        return DomainTradingPair(
            name=self.trading_pair.name,
            symbol=self.symbol,
            type=self.trading_pair.type,
            min_amount=self.min_amount,
            max_amount=self.max_amount,
            fee_percent=self.taker_fee or self.fee_percent,
        )


class Candle(models.Model):
    timestamp = models.DateTimeField(
        verbose_name="Временная метка",
    )
    high = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Максимальная цена",
    )
    low = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Минимальная цена",
    )
    open = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Цена открытия",
    )
    close = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Цена закрытия",
    )
    volume = models.DecimalField(
        max_digits=38,
        decimal_places=18,
        verbose_name="Объём торгов",
    )

    class Meta:
        verbose_name = "Свеча"
        verbose_name_plural = "Свечи"
        abstract = True

    def __str__(self):
        return f"date:{self.timestamp}, open:{self.open}, close:{self.close}"

    def instantiate(self) -> DomainCandle:
        """
        Возвращает экземпляр свечи с заполненными полями.
        """
        return DomainCandle(
            dt_unix=self.dt_unix,
            high=self.high,
            low=self.low,
            open=self.open,
            close=self.close,
            volume=self.volume,
        )

    @property
    def dt_unix(self) -> int:
        """
        Возвращает временную метку в формате UNIX (в млс).
        """
        naive_ts = timezone.make_naive(self.timestamp)
        return int(naive_ts.timestamp() * 1000)


class ExchangeCandle(Candle):
    exchange = models.ForeignKey(
        Exchange,
        on_delete=models.CASCADE,
        verbose_name="Биржа",
    )
    timeframe = models.CharField(
        max_length=3,
        choices=Timeframe.choices,
        verbose_name="Таймфрейм",
    )
    trading_pair = models.ForeignKey(
        TradingPair,
        on_delete=models.CASCADE,
        verbose_name="Торговая пара",
    )
    timestamp = models.DateTimeField(
        verbose_name="Временная метка",
    )

    class Meta:
        verbose_name = "Свеча биржи"
        verbose_name_plural = "Свечи бирж"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "exchange",
                    "timeframe",
                    "trading_pair",
                    "timestamp",
                ],
                name="unique_candle",
            )
        ]

    def __str__(self):
        return f"date:{self.timestamp}, open:{self.open}, close:{self.close}"

    def instantiate(self) -> DomainExchangeCandle:
        return DomainExchangeCandle(
            id=self.pk,
            dt_unix=self.dt_unix,
            high=self.high,
            low=self.low,
            open=self.open,
            close=self.close,
            volume=self.volume,
        )
