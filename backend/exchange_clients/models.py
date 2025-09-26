import asyncio
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from core.utils.mixins import ActiveManagerMixin, TimeStampedMixin
from core.utils.types import OrderSide, OrderStatus, OrderType, ProxyProtocol, Timeframe
from django.db import models
from django.utils import timezone
from exchange_clients.domain import AbstractExchangeClient as DomainExchangeClient
from exchange_clients.domain import (
    ExchangeClientCandleSource as DomainExchangeClientCandleSource,
)
from exchange_clients.domain import ExchangeClientRegistry
from exchange_clients.domain.proxies import Proxy as DomainProxy
from exchange_clients.domain.schemas import (
    ExchangeClientBalance as DomainExchangeClientBalance,
)
from exchange_clients.domain.schemas import (
    ExchangeClientOrder as DomainExchangeClientOrder,
)
from exchange_clients.domain.schemas import OrderSide as DomainOrderSide
from exchange_clients.domain.schemas import OrderStatus as DomainOrderStatus
from exchange_clients.domain.schemas import OrderType as DomainOrderType
from exchanges.domain import Timeframe as DomainTimeframe
from exchanges.domain.schemas import Candle as DomainCandle
from exchanges.models import Candle, Exchange, TradingPair
from loguru import logger


class Proxy(ActiveManagerMixin, TimeStampedMixin, models.Model):
    protocol = models.CharField(
        max_length=10,
        choices=ProxyProtocol.choices,
        default=ProxyProtocol.SOCKS5,
        verbose_name="Протокол",
    )
    host = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="Хост",
    )
    port = models.IntegerField(
        verbose_name="Порт",
    )
    username = models.CharField(
        max_length=100,
        verbose_name="Имя пользователя",
    )
    password = models.CharField(
        max_length=100,
        verbose_name="Пароль",
    )
    errors = models.TextField(
        null=True,
        blank=True,
        verbose_name="Ошибки",
    )

    def __str__(self):
        return (
            f"{self.protocol}://{self.username}:{self.password}@{self.host}:{self.port}"
        )

    @property
    def is_ready(self):
        return self.is_active and not self.errors

    def instantiate(self) -> DomainProxy:
        return DomainProxy(
            protocol=self.protocol,
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
        )

    def check_obj(self):
        import requests

        try:
            proxies = {"http": str(self)}
            response = requests.get(
                "http://www.httpbin.org/ip",
                proxies=proxies,
            )
            resp_data = response.json()

            if resp_data["origin"] != self.host:
                raise Exception(
                    f'Ip address{self.host} is not equal from http://www.httpbin.org/ip {resp_data["origin"]}'
                )

        except Exception as error:
            self.errors = str(error)
        else:
            self.errors = None
        finally:
            self.save()


class ExchangeClient(ActiveManagerMixin, TimeStampedMixin, models.Model):
    name = models.CharField(
        max_length=20,
        verbose_name="Название клиента",
    )
    exchange = models.ForeignKey(
        Exchange,
        on_delete=models.CASCADE,
        verbose_name="Биржа",
        limit_choices_to={"is_active": True},
    )
    api_key = models.CharField(
        max_length=200,
        verbose_name="API ключ",
    )
    api_secret = models.CharField(
        max_length=200,
        verbose_name="API секрет",
    )
    demo = models.BooleanField(
        default=True,
        verbose_name="Демо режим",
    )
    proxy = models.ForeignKey(
        Proxy,
        models.CASCADE,
        null=True,
        blank=True,
        verbose_name="Прокси",
    )

    class Meta:
        verbose_name = "Клиент Биржи"
        verbose_name_plural = "Клиенты Бирж"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "api_key",
                    "api_secret",
                ],
                name="unique_exchange_client",
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.exchange})"

    def get_class(self) -> DomainExchangeClient:
        return ExchangeClientRegistry.get_class(self.exchange.class_name)

    def instantiate(self) -> DomainExchangeClient:
        cls = self.get_class()
        api_key = self.api_key.strip() if self.api_key else None
        api_secret = self.api_secret.strip() if self.api_secret else None
        proxy = self.proxy.instantiate() if self.proxy else None

        return cls(
            api_key=api_key,
            api_secret=api_secret,
            demo=self.demo,
            proxy=proxy,
        )

    def fetch_balances(self) -> List["ExchangeClientBalance"]:
        """
        Получает баланс клиента биржи и сохраняет его в базу данных.
        """

        async def fetch_balances(
            exchange_client: DomainExchangeClient,
        ) -> List[DomainExchangeClientBalance]:
            async with exchange_client:
                return await exchange_client.get_balances()

        domain_balances = asyncio.run(
            fetch_balances(exchange_client=self.instantiate())
        )

        balances = [
            ExchangeClientBalance(
                exchange_client=self,
                currency=balance.currency,
                total=balance.total,
                debt=balance.debt,
                free=balance.free,
                used=balance.used,
            )
            for balance in domain_balances
        ]

        return ExchangeClientBalance.objects.bulk_create(
            balances,
            update_conflicts=True,
            update_fields=[
                "free",
                "used",
                "debt",
                "total",
            ],
            unique_fields=[
                "exchange_client",
                "currency",
            ],
        )

    # def get_orders(
    #     self,
    #     trading_pair: Optional[str] = None,
    #     since: Optional[datetime] = None,
    #     limit: Optional[int] = None,
    #     params: Optional[dict] = None,
    # ) -> List["ExchangeClientOrder"]:
    #     exchange_client = self.instantiate()
    #     try:
    #         orders = await client.get_orders(
    #             trading_pair=trading_pair,
    #             since=since,
    #             limit=limit,
    #             params=params,
    #         )
    #     except Exception as e:
    #         logger.error(f"Ошибка получения ордеров для {trading_pair}: {e}")
    #         return []

    #     return [
    #         ExchangeClientOrder(
    #             exchange_client=self,
    #             timestamp=order.timestamp,
    #             side=order.side,
    #             price=order.price,
    #             amount=order.amount,
    #             status=order.status,
    #         )
    #         for order in orders
    #     ]

    # def fetch_orders(
    #     self,
    #     trading_pair: Optional[str] = None,
    #     since: Optional[datetime] = None,
    #     limit: Optional[int] = None,
    #     params: Optional[dict] = None,
    # ) -> List["ExchangeClientOrder"]:
    #     orders = self.get_orders(
    #         trading_pair=trading_pair, since=since, limit=limit, params=params
    #     )
    #     return ExchangeClientOrder.objects.bulk_create(
    #         orders,
    #         update_conflicts=True,
    #         update_fields=["status", "price", "amount"],
    #         unique_fields=["exchange_client", "exchange_order_id"],
    #     )


class ExchangeClientBalance(TimeStampedMixin, models.Model):
    exchange_client = models.ForeignKey(
        ExchangeClient,
        on_delete=models.CASCADE,
        verbose_name="Клиент биржи",
    )
    currency = models.CharField(
        max_length=10,
        verbose_name="Валюта",
    )
    total = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Всего",
    )
    debt = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Долг",
    )
    free = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Свободно",
    )
    used = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Использовано",
    )

    class Meta:
        verbose_name = "Баланс Клиента Биржи"
        verbose_name_plural = "Балансы Клиентов Бирж"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "exchange_client",
                    "currency",
                ],
                name="unique_balance",
            )
        ]


class ExchangeClientOrder(models.Model):
    exchange_client = models.ForeignKey(
        ExchangeClient,
        on_delete=models.CASCADE,
        verbose_name="Клиент биржи",
    )
    exchange_order_id = models.CharField(
        max_length=50,
        verbose_name="ID ордера на бирже",
        db_index=True,
    )
    status = models.CharField(
        max_length=10,
        choices=OrderStatus.choices,
        default=OrderStatus.OPENED,
        verbose_name="Статус ордера",
    )
    type = models.CharField(
        max_length=10,
        choices=OrderType.choices,
        default=OrderType.MARKET,
        verbose_name="Тип ордера",
    )
    side = models.CharField(
        max_length=4,
        choices=OrderSide.choices,
        verbose_name="Сторона (BUY/SELL)",
    )
    timestamp = models.DateTimeField(
        verbose_name="Время ордера",
        db_index=True,
    )
    trading_pair = models.ForeignKey(
        TradingPair,
        on_delete=models.CASCADE,
        verbose_name="Торговая пара",
    )
    price = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Цена",
    )
    amount = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Кол-во",
    )
    fee = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        default=0.0,
        verbose_name="Комиссия",
    )

    class Meta:
        verbose_name = "Ордер Клиента"
        verbose_name_plural = "Ордер Клиента"

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "exchange_client",
                    "trading_pair",
                    "timestamp",
                    "exchange_order_id",
                ],
                name="unique_exchange_order",
            )
        ]

    def instantiate(self) -> DomainExchangeClientOrder:
        return DomainExchangeClientOrder(
            timestamp=self.timestamp,
            side=DomainOrderSide(self.side),
            status=DomainOrderStatus(self.status),
            type=DomainOrderType(self.type),
            trading_pair=self.trading_pair.instantiate(),
            exchange_order_id=self.exchange_order_id,
            price=self.price,
            amount=self.amount,
            fee=self.fee,
        )

    @property
    def volume(self) -> Decimal:
        return self.instantiate().volume


class ExchangeClientCandleSource(ActiveManagerMixin, TimeStampedMixin, models.Model):
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

    @property
    def total_candles_count(self):
        return self.candles.count()

    @property
    def candles(self):
        return Candle.objects.filter(
            exchange=self.exchange_client.exchange,
            timeframe=self.timeframe,
            trading_pair=self.trading_pair,
        )

    def instantiate(
        self, domain_exchange_client: Optional[DomainExchangeClient] = None
    ) -> DomainExchangeClientCandleSource:
        exchange_client = domain_exchange_client or self.exchange_client.instantiate()
        return DomainExchangeClientCandleSource(
            exchange_client=exchange_client,
            trading_pair=self.trading_pair.instantiate(),
            timeframe=DomainTimeframe(self.timeframe),
        )

    def __str__(self):
        return f"{self.exchange_client} | {self.trading_pair} | {self.timeframe}"

    def get_candles(
        self,
        limit: Optional[int] = None,
        since: Optional[datetime] = None,
    ) -> List[Candle]:
        tp = self.trading_pair
        tf = Timeframe(self.timeframe)
        logger.info(f"📡 Получение свечей: {self.exchange_client.name} | {tp} | {tf}")

        default_count = 999
        now = timezone.now()
        if since and since > now:
            raise ValueError("Since не может быть в будущем.")

        total_limit = limit or default_count
        if since:
            step_delta = tf.timedelta() * default_count
            total_steps = min(
                ((now - since) // step_delta) + 1, (total_limit // default_count) + 1
            )
        else:
            total_steps = (
                1
                if total_limit <= default_count
                else (total_limit // default_count) + 1
            )

        try:

            async def get_candles(
                exchange_client: DomainExchangeClient,
                trading_pair: TradingPair,
                timeframe: Timeframe,
                since: Optional[datetime],
                limit: Optional[int],
            ) -> List[DomainCandle]:
                async with exchange_client:
                    tasks = []
                    for step in range(total_steps):
                        step_since = since + step * step_delta if since else None
                        step_limit = (
                            min(default_count, total_limit - step * default_count)
                            if limit
                            else default_count
                        )
                        tasks.append(
                            exchange_client.get_candles(
                                trading_pair=trading_pair.symbol,
                                timeframe=timeframe.value,
                                since=step_since,
                                limit=step_limit,
                            )
                        )
                    results = await asyncio.gather(*tasks)
                    return [c for sublist in results for c in sublist]

            candles: List[DomainCandle] = asyncio.run(
                get_candles(
                    exchange_client=self.exchange_client.instantiate(),
                    trading_pair=self.trading_pair.instantiate(),
                    timeframe=DomainTimeframe(self.timeframe),
                    since=since,
                    limit=limit,
                )
            )
            logger.success(f"✅ Получено {len(candles)} свечей")
        except Exception as e:
            self.errors = str(e)
            logger.error(f"❌ Ошибка получения свечей: {e}")
            return []
        else:
            self.errors = None
        finally:
            self.save()

        # Преобразовать в Django объекты
        return [
            Candle(
                exchange=self.exchange_client.exchange,
                timeframe=tf,
                trading_pair=tp,
                timestamp=c.timestamp,
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
                volume=c.volume,
            )
            for c in candles
        ]

    def fetch_candles(
        self,
        limit: Optional[int] = None,
        since: Optional[datetime] = None,
    ) -> List[Candle]:
        candles = self.get_candles(limit=limit, since=since)
        return Candle.objects.bulk_create(
            candles,
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
