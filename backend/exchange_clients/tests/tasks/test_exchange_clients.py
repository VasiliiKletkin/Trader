from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from exchange_clients import tasks
from exchange_clients.models import ExchangeClient, ExchangeClientBalance
from exchanges.domain import BybitExchange
from exchanges.models import Exchange


def build_exchange() -> Exchange:
    exchange, _ = Exchange.objects.get_or_create(
        class_name=BybitExchange.__name__,
        defaults={"name": "Bybit"},
    )
    return exchange


def build_exchange_client(
    exchange: Exchange, api_key: str, api_secret: str
) -> ExchangeClient:
    return ExchangeClient.objects.create(
        exchange=exchange,
        name=f"Test EC {api_key}",
        arguments={"api_key": api_key, "api_secret": api_secret},
    )


def _make_balances(currencies: list[tuple[str, Decimal]]):
    return [
        SimpleNamespace(
            currency=cur,
            total=total,
            debt=Decimal("0"),
            free=total,
            used=Decimal("0"),
        )
        for cur, total in currencies
    ]


@pytest.fixture(autouse=True)
def _mock_bus_client():
    with patch(
        "exchange_clients.domain.messages.rpc_client.RPCExchangeClient.get_balances",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock:
        yield mock


@pytest.mark.django_db
class TestExchangeClientTasks:
    def test_exchange_clients_fetch_balances_no_clients(self):
        bulk_create = ExchangeClientBalance.objects.bulk_create
        with patch.object(
            ExchangeClientBalance.objects, "bulk_create", wraps=bulk_create
        ) as mock_bc:
            tasks.exchange_clients_fetch_balances()
            mock_bc.assert_not_called()

    def test_exchange_clients_fetch_balances_bulk_create(self, _mock_bus_client):
        exchange = build_exchange()
        build_exchange_client(exchange, "key_1", "secret_1")
        build_exchange_client(exchange, "key_2", "secret_2")

        balances_by_call = [
            _make_balances([("USDT", Decimal("10"))]),
            _make_balances([("BTC", Decimal("1")), ("ETH", Decimal("2"))]),
        ]
        _mock_bus_client.side_effect = balances_by_call

        created = {}

        def fake_bulk_create(objects, **kwargs):
            created["objects"] = list(objects)
            created["kwargs"] = kwargs

        with patch.object(
            ExchangeClientBalance.objects, "bulk_create", fake_bulk_create
        ):
            tasks.exchange_clients_fetch_balances()

        assert len(created["objects"]) == 3
        assert {obj.currency for obj in created["objects"]} == {"USDT", "BTC", "ETH"}
        assert created["kwargs"]["unique_fields"] == ["exchange_client", "currency"]

    def test_exchange_clients_fetch_balances_query_count_no_clients(self):
        """Без клиентов — только 1 запрос для получения списка."""
        with CaptureQueriesContext(connection) as queries:
            tasks.exchange_clients_fetch_balances()

        assert len(queries) == 1

    def test_exchange_clients_fetch_balances_query_count_with_clients(
        self, _mock_bus_client
    ):
        """Количество запросов не растёт с количеством клиентов."""
        exchange = build_exchange()
        build_exchange_client(exchange, "key_1", "secret_1")
        build_exchange_client(exchange, "key_2", "secret_2")
        build_exchange_client(exchange, "key_3", "secret_3")

        _mock_bus_client.return_value = _make_balances([("USDT", Decimal("100"))])

        with CaptureQueriesContext(connection) as queries:
            tasks.exchange_clients_fetch_balances()

        # 1. SELECT ExchangeClient + 2. INSERT bulk_create
        assert len(queries) == 2

    def test_exchange_clients_fetch_balances_query_count_scales(self, _mock_bus_client):
        """Количество запросов не зависит от количества клиентов."""
        exchange = build_exchange()

        _mock_bus_client.return_value = _make_balances([("USDT", Decimal("50"))])

        for count in [1, 5, 10]:
            ExchangeClient.objects.all().delete()
            for i in range(count):
                build_exchange_client(exchange, f"key_{i}", f"secret_{i}")

            with CaptureQueriesContext(connection) as queries:
                tasks.exchange_clients_fetch_balances()

            assert len(queries) == 2, (
                f"Для {count} клиентов ожидалось 2 запроса, получено {len(queries)}"
            )

    def test_exchange_clients_fetch_balances_update_existing(self, _mock_bus_client):
        """При повторном вызове балансы обновляются, а не дублируются."""
        exchange = build_exchange()
        client = build_exchange_client(exchange, "key", "secret")

        ExchangeClientBalance.objects.create(
            exchange_client=client,
            currency="USDT",
            total=Decimal("100"),
            debt=Decimal("0"),
            free=Decimal("100"),
            used=Decimal("0"),
        )

        _mock_bus_client.return_value = [
            SimpleNamespace(
                currency="USDT",
                total=Decimal("200"),
                debt=Decimal("0"),
                free=Decimal("150"),
                used=Decimal("50"),
            )
        ]

        tasks.exchange_clients_fetch_balances()

        balances = ExchangeClientBalance.objects.filter(
            exchange_client=client, currency="USDT"
        )
        assert balances.count() == 1

        updated_balance = balances.first()
        assert updated_balance.total == Decimal("200")
        assert updated_balance.free == Decimal("150")
        assert updated_balance.used == Decimal("50")
