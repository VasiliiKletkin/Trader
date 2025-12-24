"""Тесты ORM модели CandleProvider с анализом SQL-запросов."""

import pytest
from decimal import Decimal
from django.test import TestCase

from candle_providers.models import CandleProvider
from candle_providers.domain.providers import (
    PlainCandleProvider,
    DivisionCandleProvider,
    MinusCandleProvider,
)


pytestmark = pytest.mark.django_db


@pytest.fixture
def create_test_data(db):
    """Фикстура для создания тестовых данных."""
    from exchanges.models import Exchange, TradingPair, ExchangeTradingPair
    from exchange_clients.models import ExchangeClient
    from candle_sources.models import CandleSource

    exchange1 = Exchange.objects.create(name="Binance", class_name="BinanceClient")
    exchange2 = Exchange.objects.create(name="ByBit", class_name="BybitClient")

    trading_pair = TradingPair.objects.create(
        name="BTC/USDT",
        symbol="BTC/USDT",
        min_amount=Decimal("0.001"),
        max_amount=Decimal("1000"),
        fee_percent=Decimal("0.1"),
    )

    ExchangeTradingPair.objects.create(
        exchange=exchange1, trading_pair=trading_pair, symbol="BTC/USDT:USDT"
    )
    ExchangeTradingPair.objects.create(
        exchange=exchange2, trading_pair=trading_pair, symbol="BTC/USDT"
    )

    client1 = ExchangeClient.objects.create(
        exchange=exchange1,
        api_key="test_key_1",
        api_secret="test_secret_1",
        name="Test Client 1",
    )
    client2 = ExchangeClient.objects.create(
        exchange=exchange2,
        api_key="test_key_2",
        api_secret="test_secret_2",
        name="Test Client 2",
    )

    source1 = CandleSource.objects.create(
        exchange_client=client1, trading_pair=trading_pair, timeframe="1h"
    )
    source2 = CandleSource.objects.create(
        exchange_client=client2, trading_pair=trading_pair, timeframe="1h"
    )

    return {
        "source1": source1,
        "source2": source2,
        "trading_pair": trading_pair,
    }


class TestCandleProviderModel(TestCase):
    """Тесты ORM модели CandleProvider."""

    def test_create_plain_provider(self):
        """Тест создания PlainCandleProvider."""
        from exchanges.models import Exchange, TradingPair
        from exchange_clients.models import ExchangeClient
        from candle_sources.models import CandleSource

        exchange = Exchange.objects.create(name="Binance", class_name="BinanceClient")
        trading_pair = TradingPair.objects.create(
            name="BTC/USDT",
            symbol="BTC/USDT",
            min_amount=Decimal("0.001"),
            max_amount=Decimal("1000"),
            fee_percent=Decimal("0.1"),
        )
        client = ExchangeClient.objects.create(
            exchange=exchange,
            api_key="test_key",
            api_secret="test_secret",
            name="Test Client",
        )
        source = CandleSource.objects.create(
            exchange_client=client, trading_pair=trading_pair, timeframe="1h"
        )

        provider = CandleProvider.objects.create(
            class_name="PlainCandleProvider",
            primary_source=source,
        )

        self.assertEqual(provider.class_name, "PlainCandleProvider")
        self.assertEqual(provider.primary_source, source)
        self.assertIsNone(provider.secondary_source)


class TestCandleProviderInstantiate:
    """Тесты метода instantiate() с анализом SQL-запросов."""

    def test_plain_provider_instantiate_query_count(self, create_test_data, django_assert_num_queries):
        """Тест количества запросов при создании PlainCandleProvider из ORM."""
        data = create_test_data

        provider_orm = CandleProvider.objects.create(
            class_name="PlainCandleProvider",
            primary_source=data["source1"],
        )

        # Проверяем количество SQL-запросов при instantiate()
        with django_assert_num_queries(0):  # Не должно быть доп. запросов
            provider_domain = provider_orm.instantiate()

        assert isinstance(provider_domain, PlainCandleProvider)
        assert provider_domain.source_id == data["source1"].id

    def test_division_provider_instantiate_query_count(self, create_test_data, django_assert_num_queries):
        """Тест количества запросов при создании DivisionCandleProvider из ORM."""
        data = create_test_data

        provider_orm = CandleProvider.objects.create(
            class_name="DivisionCandleProvider",
            primary_source=data["source1"],
            secondary_source=data["source2"],
        )

        # Проверяем количество SQL-запросов при instantiate()
        with django_assert_num_queries(0):  # Не должно быть доп. запросов
            provider_domain = provider_orm.instantiate()

        assert isinstance(provider_domain, DivisionCandleProvider)

    def test_minus_provider_instantiate_query_count(self, create_test_data, django_assert_num_queries):
        """Тест количества запросов при создании MinusCandleProvider из ORM."""
        data = create_test_data

        provider_orm = CandleProvider.objects.create(
            class_name="MinusCandleProvider",
            primary_source=data["source1"],
            secondary_source=data["source2"],
        )

        with django_assert_num_queries(0):
            provider_domain = provider_orm.instantiate()

        assert isinstance(provider_domain, MinusCandleProvider)

    def test_instantiate_with_select_related(self, create_test_data, django_assert_num_queries):
        """Тест что select_related оптимизирует загрузку связей."""
        data = create_test_data

        CandleProvider.objects.create(
            class_name="DivisionCandleProvider",
            primary_source=data["source1"],
            secondary_source=data["source2"],
        )

        # С полным select_related включая trading_pair - один запрос
        with django_assert_num_queries(1):
            provider_orm = CandleProvider.objects.select_related(
                'primary_source',
                'secondary_source',
                'primary_source__exchange_client',
                'secondary_source__exchange_client',
                'primary_source__trading_pair',  # Важно!
                'secondary_source__trading_pair',  # Важно!
            ).first()

        # После загрузки - доступ без доп. запросов
        with django_assert_num_queries(0):
            _ = provider_orm.primary_source.exchange_client
            _ = provider_orm.secondary_source.exchange_client
            _ = provider_orm.primary_source.trading_pair
            _ = provider_orm.secondary_source.trading_pair
            provider_domain = provider_orm.instantiate()

        assert isinstance(provider_domain, DivisionCandleProvider)


class TestCandleProviderQueryOptimization:
    """Тесты оптимизации запросов."""

    def test_bulk_instantiate_plain_providers(self, create_test_data, django_assert_num_queries):
        """Тест массового создания domain объектов из ORM."""
        data = create_test_data

        # Создаем несколько провайдеров
        providers_orm = []
        for i in range(5):
            provider = CandleProvider.objects.create(
                class_name="PlainCandleProvider",
                primary_source=data["source1"],
            )
            providers_orm.append(provider)

        # Загружаем все с select_related за один запрос
        with django_assert_num_queries(1):
            providers_orm = list(
                CandleProvider.objects.select_related(
                    'primary_source',
                    'secondary_source'
                ).all()
            )

        # Создаем domain объекты без доп. запросов
        with django_assert_num_queries(0):
            providers_domain = [p.instantiate() for p in providers_orm]

        assert len(providers_domain) == 5
        assert all(isinstance(p, PlainCandleProvider) for p in providers_domain)

    def test_bulk_instantiate_division_providers(self, create_test_data, django_assert_num_queries):
        """Тест массового создания DivisionCandleProvider."""
        data = create_test_data

        # Создаем несколько провайдеров
        for i in range(3):
            CandleProvider.objects.create(
                class_name="DivisionCandleProvider",
                primary_source=data["source1"],
                secondary_source=data["source2"],
            )

        # Загружаем все с полным select_related
        with django_assert_num_queries(1):
            providers_orm = list(
                CandleProvider.objects.select_related(
                    'primary_source',
                    'secondary_source',
                    'primary_source__exchange_client',
                    'secondary_source__exchange_client',
                    'primary_source__trading_pair',
                    'secondary_source__trading_pair',
                ).all()
            )

        # Создаем domain объекты
        with django_assert_num_queries(0):
            providers_domain = [p.instantiate() for p in providers_orm]

        assert len(providers_domain) == 3
        assert all(isinstance(p, DivisionCandleProvider) for p in providers_domain)


class TestCandleProviderProperties:
    """Тесты свойств модели."""

    def test_timeframe_property_no_extra_queries(self, create_test_data, django_assert_num_queries):
        """Тест что свойство timeframe не вызывает доп. запросов после полной загрузки."""
        data = create_test_data

        provider = CandleProvider.objects.create(
            class_name="PlainCandleProvider",
            primary_source=data["source1"],
        )

        # Загружаем с полным select_related включая trading_pair
        provider = CandleProvider.objects.select_related(
            'primary_source',
            'primary_source__trading_pair'  # Нужно для provider.trading_pair
        ).get(id=provider.id)

        # Доступ к timeframe и trading_pair без доп. запросов
        with django_assert_num_queries(0):
            timeframe = provider.timeframe
            trading_pair = provider.trading_pair

        assert timeframe == "1h"
        assert trading_pair == data["trading_pair"]

    def test_get_class_method(self, create_test_data, django_assert_num_queries):
        """Тест метода get_class() без запросов."""
        data = create_test_data

        provider = CandleProvider.objects.create(
            class_name="PlainCandleProvider",
            primary_source=data["source1"],
        )

        # get_class не должен делать запросов
        with django_assert_num_queries(0):
            cls = provider.get_class()

        assert cls == PlainCandleProvider


class TestCandleProviderPerformance:
    """Тесты производительности."""

    def test_single_provider_total_queries(self, create_test_data, django_assert_num_queries):
        """Полный цикл: создание ORM → instantiate → domain объект."""
        data = create_test_data

        # 1. Создание ORM объекта (1 INSERT)
        with django_assert_num_queries(1):
            provider_orm = CandleProvider.objects.create(
                class_name="DivisionCandleProvider",
                primary_source=data["source1"],
                secondary_source=data["source2"],
            )

        # 2. Загрузка с полным select_related (1 SELECT)
        with django_assert_num_queries(1):
            provider_orm = CandleProvider.objects.select_related(
                'primary_source',
                'secondary_source',
                'primary_source__trading_pair',
                'secondary_source__trading_pair',
            ).get(id=provider_orm.id)

        # 3. Создание domain объекта (0 запросов)
        with django_assert_num_queries(0):
            provider_domain = provider_orm.instantiate()

        # 4. Работа с domain объектом (0 запросов)
        with django_assert_num_queries(0):
            assert isinstance(provider_domain, DivisionCandleProvider)
            assert provider_domain.source_1.source_id == data["source1"].id
            assert provider_domain.source_2.source_id == data["source2"].id

    def test_n_plus_one_problem_prevented(self, create_test_data, django_assert_num_queries):
        """Тест что N+1 проблема предотвращена с помощью select_related."""
        data = create_test_data

        # Создаем 10 провайдеров
        for i in range(10):
            CandleProvider.objects.create(
                class_name="DivisionCandleProvider",
                primary_source=data["source1"],
                secondary_source=data["source2"],
            )

        # С полным select_related - всего 1 запрос для всех провайдеров
        with django_assert_num_queries(1):
            providers = list(
                CandleProvider.objects.select_related(
                    'primary_source',
                    'secondary_source',
                    'primary_source__trading_pair',  # Важно!
                    'secondary_source__trading_pair',  # Важно!
                ).all()
            )

        # Доступ ко всем связям без доп. запросов
        with django_assert_num_queries(0):
            for provider in providers:
                _ = provider.primary_source
                _ = provider.secondary_source
                _ = provider.timeframe
                _ = provider.trading_pair

        assert len(providers) == 10
