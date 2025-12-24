from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from exchange_clients.domain import ByBitExchangeClient
from exchange_clients.models import ExchangeClient, ExchangeClientBalance
from exchange_clients import tasks
from exchanges.models import Exchange


def build_exchange() -> Exchange:
    return Exchange.objects.create(
        name="Bybit",
        class_name=ByBitExchangeClient.__name__,
    )


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
        monkeypatch.setattr(ExchangeClientBalance.objects, "bulk_create", bulk_create_mock)

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

        monkeypatch.setattr(ExchangeClientBalance.objects, "bulk_create", fake_bulk_create)

        tasks.exchange_clients_fetch_balances()

        assert sorted(instantiate_calls) == sorted([client_1.pk, client_2.pk])
        assert len(created["objects"]) == 3
        assert {obj.currency for obj in created["objects"]} == {"USDT", "BTC", "ETH"}
        assert created["kwargs"]["unique_fields"] == ["exchange_client", "currency"]
