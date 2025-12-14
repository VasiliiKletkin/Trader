from decimal import Decimal

from core.utils.mixins import ActiveManagerMixin, TimeStampedMixin
from core.utils.types import Timeframe
from django.db import models
from django.utils import timezone
from exchange_clients.domain import ExchangeClientRegistry
from exchanges.domain import Candle as DomainCandle
from exchanges.domain import TradingPair as DomainTradingPair


class Exchange(ActiveManagerMixin, TimeStampedMixin, models.Model):
    name = models.CharField(
        max_length=20,
        unique=True,
        verbose_name="Название биржи",
    )
    class_name = models.CharField(
        max_length=30,
        choices=ExchangeClientRegistry.get_choices,
        unique=True,
        verbose_name="Класс клиента",
    )

    class Meta:
        verbose_name = "Биржа"
        verbose_name_plural = "Биржи"

    def __str__(self):
        return self.name


class TradingPair(TimeStampedMixin, models.Model):
    name = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Название торговой пары",
        help_text="Например BTC/USDT",
        default="BTC/USDT",
    )
    symbol = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Значение торговой пары",
        help_text="Формат:BTC/USDT:USDT",
        default="BTC/USDT:USDT",
    )
    min_amount = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        default=Decimal("0.001"),
        verbose_name="Минимальное количетсво",
        help_text="Минимальное количетсво для создания ордера",
    )
    max_amount = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        default=Decimal("1000000"),
        verbose_name="Максимальное количетсво",
        help_text="Максимальное количетсво для создания ордера",
    )
    fee_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.1"),
        verbose_name="Процентная комиссия",
        help_text="Процентная комиссия за сделку на данной торговой паре",
    )

    class Meta:
        verbose_name = "Торговая пара"
        verbose_name_plural = "Торговые пары"

    def __str__(self):
        return self.name

    def instantiate(self, exchange: Exchange = None) -> DomainTradingPair:
        if exchange:
            exchange_trading_pair = ExchangeTradingPair.objects.filter(
                exchange=exchange, trading_pair=self
            ).first()
            if exchange_trading_pair:
                return DomainTradingPair(
                    name=self.name,
                    symbol=exchange_trading_pair.symbol,
                    min_amount=exchange_trading_pair.min_amount,
                    max_amount=exchange_trading_pair.max_amount,
                    fee_percent=exchange_trading_pair.fee_percent,
                )
        return DomainTradingPair(
            name=self.name,
            symbol=self.symbol,
            min_amount=self.min_amount,
            max_amount=self.max_amount,
            fee_percent=self.fee_percent,
        )


class ExchangeTradingPair(TimeStampedMixin, models.Model):
    exchange = models.ForeignKey(
        Exchange,
        on_delete=models.CASCADE,
        verbose_name="Биржа",
    )
    trading_pair = models.ForeignKey(
        TradingPair,
        on_delete=models.CASCADE,
        verbose_name="Торговая пара",
    )
    symbol = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Значение торговой пары",
        help_text="Формат:BTC/USDT:USDT",
        default="BTC/USDT:USDT",
    )
    min_amount = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        default=Decimal("0.001"),
        verbose_name="Минимальное количетсво",
        help_text="Минимальное количетсво для создания ордера",
    )
    max_amount = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        default=Decimal("1000000"),
        verbose_name="Максимальное количетсво",
        help_text="Максимальное количетсво для создания ордера",
    )
    fee_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.1"),
        verbose_name="Процентная комиссия",
        help_text="Процентная комиссия за сделку на данной торговой паре",
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


class Candle(models.Model):
    timestamp = models.DateTimeField(
        verbose_name="Временная метка",
        db_index=True,
    )
    high = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Максимальная цена за период свечи",
    )
    low = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Минимальная цена за период свечи",
    )
    open = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Цена открытия свечи",
    )
    close = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Цена закрытия свечи",
    )
    volume = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Объём за период свечи",
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
            ids=[self.pk],
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
        db_index=True,
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
