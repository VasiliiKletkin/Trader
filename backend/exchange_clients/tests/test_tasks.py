from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from exchange_clients import tasks
from exchange_clients.domain import ByBitExchangeClient
from exchange_clients.models import ExchangeClient, ExchangeClientBalance
from exchanges.models import Exchange


def build_exchange() -> Exchange:
    exchange, _ = Exchange.objects.get_or_create(
        class_name=ByBitExchangeClient.__name__,
        defaults={"name": "Bybit"},
    )
    return exchange


def build_exchange_client(
    exchange: Exchange, api_key: str, api_secret: str
) -> ExchangeClient:
    return ExchangeClient.objects.create(
        exchange=exchange,
        api_key=api_key,
        api_secret=api_secret,
        name="Test EC",
        demo=True,
    )


class FakeDomainClient:
    def __init__(self, balances):
        self._balances = balances

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get_balances(self):
        return self._balances


@pytest.mark.django_db
class TestExchangeClientTasks:
    def test_exchange_clients_fetch_balances_no_clients(self, monkeypatch):
        bulk_create_mock = MagicMock()
        monkeypatch.setattr(
            ExchangeClientBalance.objects, "bulk_create", bulk_create_mock
        )

        tasks.exchange_clients_fetch_balances()

        bulk_create_mock.assert_not_called()

    def test_exchange_clients_fetch_balances_bulk_create(self, monkeypatch):
        exchange = build_exchange()
        client_1 = build_exchange_client(exchange, "key_1", "secret_1")
        client_2 = build_exchange_client(exchange, "key_2", "secret_2")

        balances_map = {
            client_1.pk: [
                SimpleNamespace(
                    currency="USDT",
                    total=Decimal("10"),
                    debt=Decimal("0"),
                    free=Decimal("7"),
                    used=Decimal("3"),
                )
            ],
            client_2.pk: [
                SimpleNamespace(
                    currency="BTC",
                    total=Decimal("1"),
                    debt=Decimal("0"),
                    free=Decimal("1"),
                    used=Decimal("0"),
                ),
                SimpleNamespace(
                    currency="ETH",
                    total=Decimal("2"),
                    debt=Decimal("0"),
                    free=Decimal("2"),
                    used=Decimal("0"),
                ),
            ],
        }
        instantiate_calls = []

        def fake_instantiate(self):
            instantiate_calls.append(self.pk)
            return FakeDomainClient(balances_map[self.pk])

        monkeypatch.setattr(ExchangeClient, "instantiate", fake_instantiate)

        created = {}

        def fake_bulk_create(objects, **kwargs):
            created["objects"] = list(objects)
            created["kwargs"] = kwargs

        monkeypatch.setattr(
            ExchangeClientBalance.objects, "bulk_create", fake_bulk_create
        )

        tasks.exchange_clients_fetch_balances()

        assert sorted(instantiate_calls) == sorted([client_1.pk, client_2.pk])
        assert len(created["objects"]) == 3
        assert {obj.currency for obj in created["objects"]} == {"USDT", "BTC", "ETH"}
        assert created["kwargs"]["unique_fields"] == ["exchange_client", "currency"]

    def test_exchange_clients_fetch_balances_query_count_no_clients(self):
        """
        Тест количества SQL-запросов когда нет клиентов.

        Проверяет оптимизацию: должен быть только 1 запрос
        для получения списка клиентов.
        """
        with CaptureQueriesContext(connection) as queries:
            tasks.exchange_clients_fetch_balances()

        # Ожидаем: 1 запрос для select_related ExchangeClient
        assert len(queries) == 1

    def test_exchange_clients_fetch_balances_query_count_with_clients(
        self, monkeypatch
    ):
        """
        Тест количества SQL-запросов с несколькими клиентами.

        Критично: количество запросов НЕ должно расти
        с количеством клиентов благодаря bulk_create.
        """
        exchange = build_exchange()
        build_exchange_client(exchange, "key_1", "secret_1")
        build_exchange_client(exchange, "key_2", "secret_2")
        build_exchange_client(exchange, "key_3", "secret_3")

        # Mock балансов для каждого клиента
        def fake_instantiate(self):
            return FakeDomainClient(
                [
                    SimpleNamespace(
                        currency="USDT",
                        total=Decimal("100"),
                        debt=Decimal("0"),
                        free=Decimal("100"),
                        used=Decimal("0"),
                    )
                ]
            )

        monkeypatch.setattr(ExchangeClient, "instantiate", fake_instantiate)

        with CaptureQueriesContext(connection) as queries:
            tasks.exchange_clients_fetch_balances()

        # Ожидаем:
        # 1. SELECT для получения всех ExchangeClient
        #    с select_related('exchange', 'proxy')
        # 2. INSERT для bulk_create балансов
        assert len(queries) == 2

    def test_exchange_clients_fetch_balances_query_count_scales(self, monkeypatch):
        """
        Тест масштабируемости: количество запросов не зависит
        от количества клиентов.

        Проверяем с 1, 5 и 10 клиентами - должно быть 2 запроса.
        """
        exchange = build_exchange()

        def fake_instantiate(self):
            return FakeDomainClient(
                [
                    SimpleNamespace(
                        currency="USDT",
                        total=Decimal("50"),
                        debt=Decimal("0"),
                        free=Decimal("50"),
                        used=Decimal("0"),
                    )
                ]
            )

        monkeypatch.setattr(ExchangeClient, "instantiate", fake_instantiate)

        for count in [1, 5, 10]:
            # Очищаем таблицу
            ExchangeClient.objects.all().delete()

            # Создаем N клиентов
            for i in range(count):
                build_exchange_client(exchange, f"key_{i}", f"secret_{i}")

            with CaptureQueriesContext(connection) as queries:
                tasks.exchange_clients_fetch_balances()

            # Количество запросов НЕ должно зависеть от count
            assert (
                len(queries) == 2
            ), f"Для {count} клиентов ожидалось 2 запроса, получено {len(queries)}"

    def test_exchange_clients_fetch_balances_update_existing(self, monkeypatch):
        """
        Тест обновления существующих балансов через update_conflicts.

        Проверяет что при повторном вызове балансы обновляются,
        а не дублируются.
        """
        exchange = build_exchange()
        client = build_exchange_client(exchange, "key", "secret")

        # Создаем начальный баланс
        ExchangeClientBalance.objects.create(
            exchange_client=client,
            currency="USDT",
            total=Decimal("100"),
            debt=Decimal("0"),
            free=Decimal("100"),
            used=Decimal("0"),
        )

        # Mock с обновленным балансом
        def fake_instantiate(self):
            return FakeDomainClient(
                [
                    SimpleNamespace(
                        currency="USDT",
                        total=Decimal("200"),  # Обновленный баланс
                        debt=Decimal("0"),
                        free=Decimal("150"),
                        used=Decimal("50"),
                    )
                ]
            )

        monkeypatch.setattr(ExchangeClient, "instantiate", fake_instantiate)

        # Вызываем task
        tasks.exchange_clients_fetch_balances()

        # Проверяем что баланс обновился, а не продублировался
        balances = ExchangeClientBalance.objects.filter(
            exchange_client=client, currency="USDT"
        )
        assert balances.count() == 1

        updated_balance = balances.first()
        assert updated_balance.total == Decimal("200")
        assert updated_balance.free == Decimal("150")
        assert updated_balance.used == Decimal("50")
