from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from exchange_clients.domain import ByBitExchangeClient
from exchange_clients.models import ExchangeClient, ExchangeClientProxy
from exchanges.models import Exchange
from core.utils.types import ProxyProtocol


def build_exchange() -> Exchange:
    return Exchange.objects.create(name="Bybit", class_name=ByBitExchangeClient.__name__)


def build_proxy() -> ExchangeClientProxy:
    return ExchangeClientProxy.objects.create(
        protocol=ProxyProtocol.SOCKS5,
        host="127.0.0.1",
        port=9050,
        username="user",
        password="pass",
    )


def build_exchange_client(
    exchange: Exchange,
    proxy: ExchangeClientProxy | None = None,
    api_key: str = " key ",
    api_secret: str = " secret ",
) -> ExchangeClient:
    return ExchangeClient.objects.create(
        exchange=exchange,
        api_key=api_key,
        api_secret=api_secret,
        name="Test EC",
        demo=True,
        proxy=proxy,
    )


@pytest.mark.django_db
class TestExchangeClientProxyModel:
    def test_str_and_is_ready(self):
        proxy = build_proxy()

        assert str(proxy) == "socks5://user:pass@127.0.0.1:9050"
        assert proxy.is_ready is True

        proxy.errors = "timeout"
        proxy.save()
        assert proxy.is_ready is False


@pytest.mark.django_db
class TestExchangeClientModel:
    def test_instantiate_strips_keys(self):
        exchange = build_exchange()
        client = build_exchange_client(exchange, proxy=None)

        domain_client = client.instantiate()

        assert isinstance(domain_client, ByBitExchangeClient)
        assert domain_client.api_key == "key"
        assert domain_client.api_secret == "secret"

    def test_instantiate_query_count_without_select_related(self):
        exchange = build_exchange()
        client = build_exchange_client(exchange, proxy=None)

        client_db = ExchangeClient.objects.get(pk=client.pk)
        with CaptureQueriesContext(connection) as queries:
            client_db.instantiate()

        assert len(queries) == 1

    def test_instantiate_query_count_with_select_related(self):
        exchange = build_exchange()
        client = build_exchange_client(exchange, proxy=None)

        client_db = ExchangeClient.objects.select_related("exchange").get(
            pk=client.pk
        )
        with CaptureQueriesContext(connection) as queries:
            client_db.instantiate()

        assert len(queries) == 0
