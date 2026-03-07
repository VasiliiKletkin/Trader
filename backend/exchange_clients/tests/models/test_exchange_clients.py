import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from exchange_clients.domain import ByBitExchangeClient
from exchange_clients.models import ExchangeClient, ExchangeClientProxy
from exchange_clients.schemas import ProxyProtocol
from exchanges.domain import BybitExchange
from exchanges.models import Exchange


def build_exchange() -> Exchange:
    exchange, _ = Exchange.objects.get_or_create(
        class_name=BybitExchange.__name__,
        defaults={"name": "Bybit"},
    )
    return exchange


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
    api_key: str = "key",
    api_secret: str = "secret",
) -> ExchangeClient:
    return ExchangeClient.objects.create(
        exchange=exchange,
        name="Test EC",
        proxy=proxy,
        arguments={"api_key": api_key, "api_secret": api_secret},
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

        client_db = ExchangeClient.objects.select_related("exchange").get(pk=client.pk)
        with CaptureQueriesContext(connection) as queries:
            client_db.instantiate()

        assert len(queries) == 0
