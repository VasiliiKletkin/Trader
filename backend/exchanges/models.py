from datetime import datetime
from typing import List, Optional

import requests
from core.utils.mixins import ActiveManagerMixin, TimeStampedMixin
from core.utils.types import (OrderSide, OrderStatus, OrderType, ProxyProtocol,
                              Timeframe, TradingPair)
from django.db import models
from django.urls import reverse
from django.utils import timezone
from exchanges.domain.exchanges.base import (AbstractExchangeClient,
                                             ExchangeClientRegistry)
from loguru import logger


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


class ExchangeClient(ActiveManagerMixin, TimeStampedMixin, models.Model):
    name = models.CharField(max_length=20)
    class_name = models.CharField(
        max_length=30,
        choices=ExchangeClientRegistry.get_choices,
    )
    api_key = models.CharField(max_length=200)
    api_secret = models.CharField(max_length=200)
    demo = models.BooleanField(default=True)
    proxy = models.ForeignKey(Proxy, models.CASCADE, null=True, blank=True)

    class Meta:
        verbose_name = "Клиент Биржи"
        verbose_name_plural = "Клиенты Бирж"
        constraints = [
            models.UniqueConstraint(
                fields=["api_key", "api_secret"],
                name="unique_api_key_api_secret",
            )
        ]

    def __str__(self):
        return self.name

    def get_exchange_client_class(self) -> "AbstractExchangeClient":
        return ExchangeClientRegistry.get_class(self.class_name)

    def instantiate(self, **kwargs) -> "AbstractExchangeClient":
        cls = self.get_exchange_client_class()
        return cls(
            api_key=self.api_key, api_secret=self.api_secret, demo=self.demo, **kwargs
        )

    def get_orders(
        self,
        trading_pair: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: Optional[int] = None,
        params: Optional[dict] = None,
    ) -> List["ExchangeOrder"]:
        client = self.instantiate()
        try:
            orders = client.get_orders(
                trading_pair=trading_pair,
                since=since,
                limit=limit,
                params=params,
            )
        except Exception as e:
            logger.error(f"Ошибка получения ордеров для {trading_pair}: {e}")
            return []

        return [
            ExchangeOrder(
                exchange_client=self,
                timestamp=order.timestamp,
                side=order.side,
                price=order.price,
                amount=order.amount,
                status=order.status,
            )
            for order in orders
        ]

    def fetch_orders(
        self,
        trading_pair: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: Optional[int] = None,
        params: Optional[dict] = None,
    ) -> List["ExchangeOrder"]:
        orders = self.get_orders(
            trading_pair=trading_pair, since=since, limit=limit, params=params
        )
        return ExchangeOrder.objects.bulk_create(
            orders,
            update_conflicts=True,
            update_fields=["status", "price", "amount"],
            unique_fields=["exchange_client", "exchange_order_id"],
        )

    def create_market_order(
        self,
        trading_pair: TradingPair,
        side: OrderSide,
        amount: float,
        price: Optional[float] = None,
        params: Optional[dict] = None,
    ) -> "ExchangeOrder":
        """
        Создаёт ордер на бирже и сохраняет его в базу данных.
        """
        client = self.instantiate()
        created_order = client.create_market_order(
            trading_pair=trading_pair.value,
            side=side.value,
            amount=amount,
            price=price,
            params=params,
        )

        return ExchangeOrder.objects.create(
            exchange_client=self,
            trading_pair=trading_pair,
            exchange_order_id=created_order["id"],
            side=OrderSide(created_order["side"]),
            type=OrderType(created_order["type"]),
            price=created_order["price"],
            amount=created_order["amount"],
            status=OrderStatus(created_order["status"]),
            timestamp=created_order["timestamp"],
        )


class ExchangeOrder(models.Model):
    exchange_client = models.ForeignKey(
        ExchangeClient,
        on_delete=models.CASCADE,
    )
    exchange_order_id = models.CharField(max_length=50)
    timestamp = models.DateTimeField()
    status = models.CharField(
        max_length=10,
        choices=OrderStatus.choices,
        default=OrderStatus.OPEN,
    )
    type = models.CharField(
        max_length=10,
        choices=OrderType.choices,
        default=OrderType.MARKET,
    )
    side = models.CharField(
        max_length=4,
        choices=OrderSide.choices,
    )
    price = models.FloatField()
    amount = models.FloatField()

    class Meta:
        verbose_name = "История Клиента"
        verbose_name_plural = "Истории Клиента"

        constraints = [
            models.UniqueConstraint(
                fields=["exchange_client", "exchange_order_id"],
                name="unique_exchange_client_and_exchange_order_id",
            )
        ]


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

    @property
    def dt_unix(self) -> int:
        """
        Возвращает временную метку в формате UNIX (в млс).
        """
        naive_ts = make_naive(self.timestamp)
        return int(naive_ts.timestamp() * 1000)


class CandleSource(ActiveManagerMixin, TimeStampedMixin, models.Model):
    exchange_client = models.ForeignKey(
        ExchangeClient,
        on_delete=models.CASCADE,
        related_name="candle_sources",
    )
    trading_pair = models.CharField(
        max_length=20,
        choices=TradingPair.choices,
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
                fields=["exchange_client", "trading_pair", "timeframe"],
                name="unique_exchange_pair_timeframe",
            )
        ]

    def __str__(self):
        return f"{self.exchange_client.name} | {self.trading_pair} | {self.timeframe}"

    def get_absolute_url(self):
        return reverse("candle_source_detail", kwargs={"pk": self.pk})

    def get_candles(
        self,
        limit: Optional[int] = None,
        since: Optional[datetime] = None,
    ) -> List[Candle]:
        tp = TradingPair(self.trading_pair)
        tf = Timeframe(self.timeframe)

        logger.info(f"📡 Получение свечей: {self.exchange_client.name} | {tp} | {tf}")
        if since:
            logger.debug(f"🕓 С начала: {since.isoformat()}")
        if limit:
            logger.debug(f"🔢 Лимит: {limit}")
        exchange_instance = self.exchange_client.instantiate()
        try:
            candles_raw = exchange_instance.get_candles(
                trading_pair=tp.value,
                timeframe=tf.value,
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
                timestamp=timezone.localtime(c.timestamp),
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
                volume=c.volume,
            )
            for c in candles_raw
        ]

        return candles

    def fetch_candles(
        self,
        limit: Optional[int] = None,
        since: Optional[datetime] = None,
    ) -> List[Candle]:
        candles = self.get_candles(limit=limit, since=since)
        return Candle.objects.bulk_create(
            candles,
            update_conflicts=True,
            update_fields=["open", "high", "low", "close", "volume"],
            unique_fields=["candle_source", "timestamp"],
        )
