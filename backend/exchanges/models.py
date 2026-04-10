import asyncio
from decimal import Decimal

from django.db import models
from django.utils import timezone

from core.utils.models import ActiveManagerMixin, TimeStampedMixin
from exchanges.domain import Candle as DomainCandle
from exchanges.domain import Exchange as DomainExchange
from exchanges.domain import ExchangeCandle as DomainExchangeCandle
from exchanges.domain import ExchangeRegistry
from exchanges.domain import TradingPair as DomainTradingPair
from exchanges.domain.schemas import MarketType as DomainMarketType
from exchanges.schemas import CandleSourceMode, MarketType, Timeframe


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
    candle_source_mode = models.CharField(
        max_length=4,
        choices=CandleSourceMode,
        default=CandleSourceMode.WEBSOCKET,
        verbose_name="Режим получения свечей",
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

    def instantiate_public_client(self):
        """Создаёт публичный exchange client (без API-ключей) для market data."""
        from core.utils.common import get_all_init_args
        from exchange_clients.domain import ExchangeClientRegistry

        domain_exchange = self.instantiate()
        domain_exchange.rate_limit = self.rate_limit * 2

        cls = ExchangeClientRegistry.get_class(domain_exchange.client_class_name)
        # Обнуляем все credential-параметры чтобы ccxt не пытался аутентифицироваться
        credential_keys = {
            "api_key",
            "api_secret",
            "private_key",
            "passphrase",
            "wallet_address",
        }
        init_params = set(get_all_init_args(cls))
        empty_creds = dict.fromkeys(credential_keys & init_params, "")
        return cls(exchange=domain_exchange, **empty_creds)

    def fetch_trading_pairs(self, market_type: MarketType) -> list[DomainTradingPair]:
        """Получить торговые пары с биржи через ccxt."""
        domain_exchange = self.instantiate()
        return asyncio.run(
            domain_exchange.fetch_trading_pairs(
                market_type=DomainMarketType(market_type),
            )
        )

    def sync_trading_pairs(self, market_type: MarketType) -> tuple[int, int]:
        """Синхронизировать торговые пары с биржи. Возвращает (created, updated)."""
        domain_pairs = self.fetch_trading_pairs(market_type=market_type)

        created_count = 0
        updated_count = 0
        for tp in domain_pairs:
            trading_pair, _ = TradingPair.objects.get_or_create(
                name=tp.name,
                type=market_type,
            )
            _, created = ExchangeTradingPair.objects.update_or_create(
                exchange=self,
                trading_pair=trading_pair,
                defaults={
                    "symbol": tp.symbol,
                    "min_amount": tp.min_amount,
                    "max_amount": tp.max_amount,
                    "min_cost": tp.min_cost,
                    "max_cost": tp.max_cost,
                    "min_price": tp.min_price,
                    "max_price": tp.max_price,
                    "price_precision": tp.price_precision,
                    "amount_precision": tp.amount_precision,
                    "taker_fee": tp.taker_fee,
                    "maker_fee": tp.maker_fee,
                    "min_leverage": tp.min_leverage,
                    "max_leverage": tp.max_leverage,
                    "is_active": tp.is_active,
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
    type = models.CharField(
        max_length=10,
        choices=MarketType.choices,
        default=MarketType.FUTURES,
        verbose_name="Тип рынка",
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

    def instantiate(self, exchange: Exchange) -> DomainTradingPair:
        try:
            exchange_trading_pair = ExchangeTradingPair.objects.get(
                exchange=exchange, trading_pair=self
            )
            return exchange_trading_pair.instantiate()
        except ExchangeTradingPair.DoesNotExist as err:
            raise ExchangeTradingPair.DoesNotExist(
                f"ExchangeTradingPair для {self.name} на {exchange.name} не найдена"
            ) from err


class ExchangeTradingPair(ActiveManagerMixin, TimeStampedMixin, models.Model):
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
    min_cost = models.DecimalField(  # type: ignore[misc]
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Минимальная стоимость ордера",
    )
    max_cost = models.DecimalField(  # type: ignore[misc]
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Максимальная стоимость ордера",
    )
    min_price = models.DecimalField(  # type: ignore[misc]
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Минимальная цена ордера",
    )
    max_price = models.DecimalField(  # type: ignore[misc]
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Максимальная цена ордера",
    )
    price_precision = models.DecimalField(  # type: ignore[misc]
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Точность цены",
    )
    amount_precision = models.DecimalField(  # type: ignore[misc]
        max_digits=30,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name="Точность количества",
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
    min_leverage = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        default=Decimal("1"),
        verbose_name="Минимальное плечо",
        help_text="Например 1 для 1x",
    )
    max_leverage = models.DecimalField(
        max_digits=6,
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
            is_active=self.is_active,
            name=self.trading_pair.name,
            symbol=self.symbol,
            type=self.trading_pair.type,
            min_amount=self.min_amount,
            max_amount=self.max_amount,
            min_cost=self.min_cost,
            max_cost=self.max_cost,
            min_price=self.min_price,
            max_price=self.max_price,
            price_precision=self.price_precision,
            amount_precision=self.amount_precision,
            taker_fee=self.taker_fee,
            maker_fee=self.maker_fee,
            min_leverage=self.min_leverage,
            max_leverage=self.max_leverage,
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
