from decimal import Decimal

import requests
from asgiref.sync import async_to_sync
from django.db import models

from core.bus import get_bus_client
from core.utils.common import get_all_init_args
from core.utils.mixins import ActiveManagerMixin, TimeStampedMixin
from exchange_clients.domain import AbstractExchangeClient as DomainExchangeClient
from exchange_clients.domain import ExchangeClientOrder as DomainExchangeClientOrder
from exchange_clients.domain import ExchangeClientProxy as DomainExchangeClientProxy
from exchange_clients.domain import ExchangeClientRegistry
from exchange_clients.domain import OrderSide as DomainOrderSide
from exchange_clients.domain import OrderStatus as DomainOrderStatus
from exchange_clients.domain import OrderType as DomainOrderType
from exchange_clients.domain.messages import (
    CancelAllOrdersMessage,
    CreateMarketOrderMessage,
    FetchBalancesMessage,
    GetOpenOrdersMessage,
)
from exchange_clients.domain.messages.messages import GetOpenOrdersResult
from exchange_clients.schemas import OrderSide, OrderStatus, OrderType, ProxyProtocol
from exchanges.models import Exchange, TradingPair


class ExchangeClientProxy(ActiveManagerMixin, TimeStampedMixin, models.Model):
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
        blank=True,
        default="",
        verbose_name="Ошибки",
    )

    class Meta:
        verbose_name = "Прокси сервер"
        verbose_name_plural = "Прокси серверы"

    def __str__(self):
        return (
            f"{self.protocol}://{self.username}:{self.password}@{self.host}:{self.port}"
        )

    @property
    def is_ready(self):
        return self.is_active and not self.errors

    def instantiate(self) -> DomainExchangeClientProxy:
        return DomainExchangeClientProxy(
            protocol=self.protocol,
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
        )

    def check_obj(self):
        try:
            proxies = {"http": str(self)}
            response = requests.get(
                "http://www.httpbin.org/ip",
                proxies=proxies,
                timeout=10,
            )
            resp_data = response.json()

            if resp_data["origin"] != self.host:
                raise Exception(
                    f"Ip address{self.host} is not equal from http://www.httpbin.org/ip {resp_data['origin']}"
                )

        except Exception as error:
            self.errors = str(error)
        else:
            self.errors = ""
        finally:
            self.save()


class ExchangeClient(ActiveManagerMixin, TimeStampedMixin, models.Model):
    name = models.CharField(
        max_length=20,
        verbose_name="Название",
    )
    exchange = models.ForeignKey(
        Exchange,
        on_delete=models.CASCADE,
        verbose_name="Биржа",
        limit_choices_to={"is_active": True},
    )
    arguments = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Параметры (аргументы)",
    )
    proxy = models.ForeignKey(  # type: ignore[misc]
        ExchangeClientProxy,
        models.CASCADE,
        null=True,
        blank=True,
        verbose_name="Прокси",
    )

    class Meta:
        verbose_name = "Клиент биржи"
        verbose_name_plural = "Клиенты бирж"
        constraints = [
            models.UniqueConstraint(
                fields=["exchange", "name"],
                name="unique_exchange_client",
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.exchange})"

    def save(self, *args, **kwargs):
        if not self.arguments and self.exchange.pk:
            try:
                cls = self.get_class()
                _exclude = {
                    "exchange",
                    "proxy",
                    "max_candles_per_request",
                    "timeout",
                    "rate_limit",
                }
                self.arguments = {
                    k: v for k, v in get_all_init_args(cls).items() if k not in _exclude
                }
            except (KeyError, ValueError):
                pass
        super().save(*args, **kwargs)

    @property
    def is_ready(self) -> bool:
        return all(
            [
                self.is_active,
                self.exchange.is_active,
                self.proxy.is_ready if self.proxy else True,
            ]
        )

    def activate(self):
        self.is_active = True
        self.save(update_fields=["is_active"])

    def deactivate(self):
        self.is_active = False
        self.save(update_fields=["is_active"])

    def get_class(self) -> DomainExchangeClient:
        exchange = self.exchange.instantiate()
        return ExchangeClientRegistry.get_class(exchange.client_class_name)

    def instantiate(self) -> DomainExchangeClient:
        cls = self.get_class()
        return cls(  # type: ignore[operator]
            **self.arguments,
            exchange=self.exchange.instantiate(),
            proxy=self.proxy.instantiate() if self.proxy else None,
        )

    def fetch_balances(self) -> list["ExchangeClientBalance"]:
        """Получает баланс клиента биржи и сохраняет его в базу данных."""
        bus = get_bus_client()
        domain_balances = async_to_sync(bus.execute)(
            FetchBalancesMessage(exchange_client_id=self.pk),
        )

        balances = [
            ExchangeClientBalance(
                exchange_client=self,
                currency=b.currency,
                total=b.total,
                debt=b.debt,
                free=b.free,
                used=b.used,
            )
            for b in domain_balances
        ]

        return ExchangeClientBalance.objects.bulk_create(
            balances,
            update_conflicts=True,
            update_fields=[
                "free",
                "used",
                "debt",
                "total",
                "updated_at",
            ],
            unique_fields=[
                "exchange_client",
                "currency",
            ],
        )

    def get_open_orders(
        self,
        trading_pair: TradingPair,
    ) -> list[DomainExchangeClientOrder]:
        """Получает список открытых ордеров с биржи."""
        bus = get_bus_client()
        result: GetOpenOrdersResult = async_to_sync(bus.execute)(  # type: ignore[assignment]
            GetOpenOrdersMessage(
                exchange_client_id=self.pk,
                trading_pair=trading_pair.instantiate(exchange=self.exchange),
            ),
        )
        return result.orders

    def create_market_order(
        self,
        trading_pair: TradingPair,
        side: str,
        amount: Decimal,
        price: Decimal,
    ) -> "ExchangeClientOrder":
        """Создаёт рыночный ордер на бирже и сохраняет в БД."""
        bus = get_bus_client()
        domain_order = async_to_sync(bus.execute)(
            CreateMarketOrderMessage(
                exchange_client_id=self.pk,
                trading_pair=trading_pair.instantiate(exchange=self.exchange),
                side=DomainOrderSide(side),
                amount=amount,
                price=price,
            ),
        )

        return ExchangeClientOrder.objects.create(
            exchange_client=self,
            exchange_order_id=domain_order.exchange_order_id,
            status=domain_order.status,
            type=domain_order.type,
            side=domain_order.side,
            timestamp=domain_order.timestamp,
            trading_pair=trading_pair,
            price=domain_order.price,
            amount=domain_order.amount,
            cost=domain_order.cost,
            fee=domain_order.fee,
        )

    def cancel_all_orders(self, trading_pair: TradingPair) -> None:
        """Отменяет все открытые ордера на бирже."""
        bus = get_bus_client()
        async_to_sync(bus.execute)(
            CancelAllOrdersMessage(
                exchange_client_id=self.pk,
                trading_pair=trading_pair.instantiate(exchange=self.exchange),
            ),
        )

    def clear_all_orders(self):
        self.orders.all().delete()


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
        related_name="balances",
        verbose_name="Клиент биржи",
    )
    currency = models.CharField(
        max_length=10,
        verbose_name="Валюта",
    )
    debt = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Долг",
    )
    free = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Свободный баланс",
    )
    used = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Использованный баланс",
    )
    total = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Общий баланс",
    )

    class Meta:
        verbose_name = "Баланс клиента"
        verbose_name_plural = "Балансы клиентов"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "exchange_client",
                    "currency",
                ],
                name="unique_balance",
            )
        ]

    def __str__(self):
        return f"{self.exchange_client} | {self.currency} | {self.total}"


class ExchangeClientOrder(models.Model):
    exchange_client = models.ForeignKey(
        ExchangeClient,
        on_delete=models.CASCADE,
        related_name="orders",
        verbose_name="Клиент биржи",
    )
    exchange_order_id = models.CharField(
        max_length=255,
        verbose_name="ID ордера",
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
        verbose_name="Сторона ордера",
    )
    timestamp = models.DateTimeField(
        verbose_name="Время исполнения",
    )
    trading_pair = models.ForeignKey(
        TradingPair,
        on_delete=models.CASCADE,
        verbose_name="Торговая пара",
    )
    price = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Цена исполнения",
    )
    amount = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Количество актива",
    )
    cost = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        verbose_name="Стоимость ордера",
    )
    fee = models.DecimalField(
        max_digits=30,
        decimal_places=18,
        default=0.0,
        verbose_name="Комиссия за ордер",
    )

    class Meta:
        verbose_name = "Ордер Клиента"
        verbose_name_plural = "Ордера клиента"

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "exchange_client",
                    "trading_pair",
                    "exchange_order_id",
                    "timestamp",
                ],
                name="unique_exchange_order",
            )
        ]

    def __str__(self):
        return f"{self.exchange_client} | {self.side} {self.amount} @ {self.price}"

    def instantiate(self) -> DomainExchangeClientOrder:
        return DomainExchangeClientOrder(
            timestamp=self.timestamp,
            side=DomainOrderSide(self.side),
            status=DomainOrderStatus(self.status),
            type=DomainOrderType(self.type),
            trading_pair=self.trading_pair.instantiate(
                exchange=self.exchange_client.exchange
            ),
            exchange_order_id=self.exchange_order_id,
            price=self.price,
            amount=self.amount,
            cost=self.cost,
            fee=self.fee,
        )
