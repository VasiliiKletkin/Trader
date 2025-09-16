import asyncio
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

import requests
from core.utils.mixins import ActiveManagerMixin, TimeStampedMixin
from core.utils.types import OrderSide, OrderStatus, OrderType, ProxyProtocol, Timeframe
from django.db import models
from django.utils import timezone
from exchange_clients.domain import AbstractExchangeClient, ExchangeClientRegistry
from exchange_clients.domain.schemas import (
    ExchangeClientOrder as DomainExchangeClientOrder,
)
from exchange_clients.domain.schemas import OrderSide as DomainOrderSide
from exchange_clients.domain.schemas import OrderStatus as DomainOrderStatus
from exchange_clients.domain.schemas import OrderType as DomainOrderType
from exchanges.domain.schemas import Candle as DomainCandle
from exchanges.domain.schemas import TradingPair as DomainTradingPair
from exchanges.models import Candle, Exchange, TradingPair
from loguru import logger


class Proxy(ActiveManagerMixin, TimeStampedMixin, models.Model):
    protocol = models.CharField(
        max_length=10,
        choices=ProxyProtocol.choices,
        default=ProxyProtocol.SOCKS5,
        verbose_name="Протокол",
    )
    address = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="Адрес",
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
            self.errors = str(error)
        else:
            self.errors = None
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
        Proxy, models.CASCADE, null=True, blank=True, verbose_name="Прокси"
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

    def get_class(self) -> "AbstractExchangeClient":
        return ExchangeClientRegistry.get_class(self.exchange.class_name)

    def instantiate(self, **kwargs) -> "AbstractExchangeClient":
        cls = self.get_class()
        api_key = self.api_key.strip() if self.api_key is not None else None
        api_secret = self.api_secret.strip() if self.api_secret is not None else None

        return cls(
            api_key=api_key,
            api_secret=api_secret,
            demo=self.demo,
            **kwargs,
        )

    def fetch_balances(self) -> List["ExchangeClientBalance"]:
        """
        Получает баланс клиента биржи и сохраняет его в базу данных.
        """
        exchange_client = self.instantiate()

        async def _fetch_balances():
            async with exchange_client:
                return await exchange_client.get_balances()

        balances = asyncio.run(_fetch_balances())

        exchange_balances = [
            ExchangeClientBalance(
                exchange_client=self,
                currency=currency,
                amount=amount,
            )
            for currency, amount in balances.items()
        ]

        return ExchangeClientBalance.objects.bulk_create(
            exchange_balances,
            update_conflicts=True,
            update_fields=["amount"],
            unique_fields=["exchange_client", "currency"],
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
    amount = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Количество",
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
            trading_pair=DomainTradingPair(
                name=self.trading_pair.name,
                symbol=self.trading_pair.symbol,
                min_amount=self.trading_pair.min_amount,
            ),
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
        if since:
            logger.debug(f"🕓 С начала: {since.isoformat()}")
        if limit:
            logger.debug(f"🔢 Лимит: {limit}")

        default_count = 1000
        step_delta = tf.timedelta() * default_count

        now = timezone.now()
        if since and since > now:
            raise ValueError("Since не может быть в будущем.")
        if since:
            total_steps = ((now - since) // step_delta) + 1
        else:
            total_steps = 1

        if limit:
            total_steps = min(total_steps, (limit // default_count) + 1)

        try:
            exchange_client = self.exchange_client.instantiate()

            async def get_candles():
                """Запустить все шаги параллельно."""
                async with exchange_client:
                    tasks = []
                    for step in range(total_steps):
                        step_since = since + step * step_delta if since else None
                        step_limit = (
                            min(default_count, limit - step * default_count)
                            if limit
                            else default_count
                        )

                        tasks.append(
                            exchange_client.get_candles(
                                trading_pair=tp.symbol,
                                timeframe=tf.value,
                                since=step_since,
                                limit=step_limit,
                            )
                        )
                    results = await asyncio.gather(*tasks)
                    return [candle for sublist in results for candle in sublist]

            candles: DomainCandle = asyncio.run(get_candles())
        except Exception as e:
            self.errors = str(e)
            logger.error(f"❌ Ошибка получения свечей: {e}")
        else:
            self.errors = None
        finally:
            self.save()
        if self.errors:
            return []

        logger.success(f"✅ Получено {len(candles)} свечей")

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
            update_fields=["open", "high", "low", "close", "volume"],
            unique_fields=["exchange", "timeframe", "trading_pair", "timestamp"],
        )
