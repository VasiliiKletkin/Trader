"""
Тесты для провайдеров свечей.

Покрывает всю функциональность domain-слоя:
- PlainCandleProvider - прямые свечи с биржи
- DivisionCandleProvider - синтетические свечи через деление (арбитраж)
- MinusCandleProvider - синтетические свечи через вычитание (спред)
- ProviderCandle - обертка для свечей с source_candles
- CandleProviderRegistry - регистрация провайдеров
"""

import pytest
from datetime import timedelta
from decimal import Decimal

from candle_sources.models import CandleSource
from exchanges.domain import ExchangeCandle, Timeframe
from candle_providers.domain import ProviderCandle, CandleProviderRegistry
from candle_providers.domain.providers import (
    PlainCandleProvider,
    DivisionCandleProvider,
    MinusCandleProvider,
)


class TestCandleProviderRegistry:
    """Тесты для реестра провайдеров свечей (не требует БД)"""

    def test_registry_contains_all_providers(self):
        """Проверяем, что все провайдеры зарегистрированы"""
        assert "PlainCandleProvider" in CandleProviderRegistry._registry
        assert "DivisionCandleProvider" in CandleProviderRegistry._registry
        assert "MinusCandleProvider" in CandleProviderRegistry._registry

    def test_registry_get_class(self):
        """Проверяем получение класса по имени"""
        cls = CandleProviderRegistry.get_class("PlainCandleProvider")
        assert cls == PlainCandleProvider

        cls = CandleProviderRegistry.get_class("DivisionCandleProvider")
        assert cls == DivisionCandleProvider

        cls = CandleProviderRegistry.get_class("MinusCandleProvider")
        assert cls == MinusCandleProvider

    def test_registry_get_choices(self):
        """Проверяем формирование choices для Django"""
        choices = CandleProviderRegistry.get_choices()
        assert len(choices) == 3
        assert ("PlainCandleProvider", "PlainCandleProvider") in choices
        assert ("DivisionCandleProvider", "DivisionCandleProvider") in choices
        assert ("MinusCandleProvider", "MinusCandleProvider") in choices


class TestProviderCandle:
    """Тесты для схемы ProviderCandle (не требует БД)"""

    def test_provider_candle_with_single_source(self):
        """Тест создания ProviderCandle с одной source candle"""
        source = ExchangeCandle(
            id=1,
            dt_unix=1704067200,
            open=Decimal("50000"),
            high=Decimal("51000"),
            low=Decimal("49000"),
            close=Decimal("50500"),
            volume=Decimal("100"),
        )

        candle = ProviderCandle(
            dt_unix=1704067200,
            open=Decimal("50000"),
            high=Decimal("51000"),
            low=Decimal("49000"),
            close=Decimal("50500"),
            volume=Decimal("100"),
            first_candle=source,
            second_candle=None,
        )

        assert candle.first_candle == source
        assert candle.second_candle is None
        assert candle.open == Decimal("50000")
        assert candle.close == Decimal("50500")

    def test_provider_candle_with_two_sources(self):
        """Тест создания ProviderCandle с двумя source candles"""
        source1 = ExchangeCandle(
            id=1,
            dt_unix=1704067200,
            open=Decimal("50000"),
            high=Decimal("51000"),
            low=Decimal("49000"),
            close=Decimal("50500"),
            volume=Decimal("100"),
        )
        source2 = ExchangeCandle(
            id=2,
            dt_unix=1704067200,
            open=Decimal("40000"),
            high=Decimal("41000"),
            low=Decimal("39000"),
            close=Decimal("40500"),
            volume=Decimal("90"),
        )

        candle = ProviderCandle(
            dt_unix=1704067200,
            open=Decimal("1.25"),  # 50000 / 40000
            high=Decimal("1.244"),  # 51000 / 41000
            low=Decimal("1.256"),  # 49000 / 39000
            close=Decimal("1.247"),  # 50500 / 40500
            volume=Decimal("90"),  # min(100, 90)
            first_candle=source1,
            second_candle=source2,
        )

        assert candle.first_candle == source1
        assert candle.second_candle == source2
        assert candle.volume == Decimal("90")


@pytest.mark.django_db
class TestPlainCandleProvider:
    """Тесты для PlainCandleProvider"""

    def test_provider_initialization(self, create_exchange_candles):
        """Тест инициализации провайдера"""
        data = create_exchange_candles
        provider = PlainCandleProvider(data["source1"])

        assert provider.source_id == data["source1"].id
        assert provider.source == data["source1"]

    def test_get_candle_returns_provider_candle(self, create_exchange_candles):
        """Тест что get_candle возвращает ProviderCandle"""
        data = create_exchange_candles
        provider = PlainCandleProvider(data["source1"])

        candle = provider.get_candle(data["candles1"][0].instantiate())

        assert isinstance(candle, ProviderCandle)
        assert candle.first_candle is not None
        assert candle.second_candle is None

    def test_get_candle_preserves_data(self, create_exchange_candles):
        """Тест что get_candle сохраняет данные свечи"""
        data = create_exchange_candles
        provider = PlainCandleProvider(data["source1"])

        source_candle = data["candles1"][0].instantiate()
        candle = provider.get_candle(source_candle)

        assert candle.first_candle.id == data["candles1"][0].id
        assert candle.timestamp == data["base_time"]
        assert candle.open == source_candle.open
        assert candle.high == source_candle.high
        assert candle.low == source_candle.low
        assert candle.close == source_candle.close
        assert candle.volume == source_candle.volume

    def test_get_candles_returns_list(self, create_exchange_candles):
        """Тест получения списка свечей"""
        data = create_exchange_candles
        provider = PlainCandleProvider(data["source1"])

        start = data["base_time"]
        end = data["base_time"] + timedelta(hours=4)

        candles = provider.get_candles(start, end)

        assert len(candles) == 5
        assert all(isinstance(c, ProviderCandle) for c in candles)

    def test_get_candles_sorted_by_timestamp(self, create_exchange_candles):
        """Тест что свечи отсортированы по timestamp"""
        data = create_exchange_candles
        provider = PlainCandleProvider(data["source1"])

        start = data["base_time"]
        end = data["base_time"] + timedelta(hours=4)

        candles = provider.get_candles(start, end)

        for i in range(len(candles) - 1):
            assert candles[i].timestamp <= candles[i + 1].timestamp

    def test_get_candles_all_have_single_source(self, create_exchange_candles):
        """Тест что все свечи имеют только first_candle"""
        data = create_exchange_candles
        provider = PlainCandleProvider(data["source1"])

        start = data["base_time"]
        end = data["base_time"] + timedelta(hours=4)

        candles = provider.get_candles(start, end)

        assert all(c.first_candle is not None for c in candles)
        assert all(c.second_candle is None for c in candles)

    def test_get_last_candles_returns_correct_count(self, create_exchange_candles):
        """Тест получения последних N свечей"""
        data = create_exchange_candles
        provider = PlainCandleProvider(data["source1"])

        candles = provider.get_last_candles(3)

        assert len(candles) == 3
        assert all(isinstance(c, ProviderCandle) for c in candles)

    def test_get_last_candles_sorted_ascending(self, create_exchange_candles):
        """Тест что последние свечи отсортированы от старых к новым"""
        data = create_exchange_candles
        provider = PlainCandleProvider(data["source1"])

        candles = provider.get_last_candles(3)

        assert candles[0].timestamp < candles[-1].timestamp

    def test_get_last_candles_returns_latest(self, create_exchange_candles):
        """Тест что возвращаются действительно последние свечи"""
        data = create_exchange_candles
        provider = PlainCandleProvider(data["source1"])

        candles = provider.get_last_candles(3)

        # Проверяем, что последняя свеча - это самая новая свеча в БД
        assert candles[-1].first_candle.id == data["candles1"][-1].id

    def test_get_candle_iterator_yields_all_candles(self, create_exchange_candles):
        """Тест что итератор возвращает все свечи"""
        data = create_exchange_candles
        provider = PlainCandleProvider(data["source1"])

        start = data["base_time"]
        end = data["base_time"] + timedelta(hours=9)

        candles = list(provider.get_candle_iterator(start, end))

        assert len(candles) == 10

    def test_get_candle_iterator_memory_efficient(self, create_exchange_candles):
        """Тест что итератор работает без загрузки всех данных в память"""
        data = create_exchange_candles
        provider = PlainCandleProvider(data["source1"])

        start = data["base_time"]
        end = data["base_time"] + timedelta(hours=9)

        # Итератор должен быть генератором
        iterator = provider.get_candle_iterator(start, end)
        assert hasattr(iterator, "__iter__")
        assert hasattr(iterator, "__next__")

    def test_get_candle_iterator_returns_provider_candles(
        self, create_exchange_candles
    ):
        """Тест что итератор возвращает ProviderCandle"""
        data = create_exchange_candles
        provider = PlainCandleProvider(data["source1"])

        start = data["base_time"]
        end = data["base_time"] + timedelta(hours=9)

        candles = list(provider.get_candle_iterator(start, end))

        assert all(isinstance(c, ProviderCandle) for c in candles)
        assert all(c.first_candle is not None for c in candles)
        assert all(c.second_candle is None for c in candles)


@pytest.mark.django_db
class TestDivisionCandleProvider:
    """Тесты для DivisionCandleProvider"""

    def test_provider_initialization(self, create_exchange_candles):
        """Тест инициализации провайдера"""
        data = create_exchange_candles

        provider = DivisionCandleProvider(data["source1"], data["source2"])

        assert isinstance(provider.source_1, CandleSource)
        assert isinstance(provider.source_2, CandleSource)
        assert provider.source_1.pk == data["source1"].id
        assert provider.source_2.pk == data["source2"].id

    def test_validation_different_timeframes_raises_error(
        self, create_exchange_candles
    ):
        """Тест валидации: разные таймфреймы должны вызвать ошибку"""
        from candle_sources.models import CandleSource

        data = create_exchange_candles

        # Создаем источник с другим таймфреймом
        source3 = CandleSource.objects.create(
            exchange_client=data["source2"].exchange_client,
            trading_pair=data["trading_pair"],
            timeframe=Timeframe.FOUR_HOURS.value,  # Другой таймфрейм!
        )

        with pytest.raises(ValueError, match="same timeframe"):
            DivisionCandleProvider(data["source1"], source3)

    def test_validation_different_trading_pairs_raises_error(
        self, create_exchange_candles
    ):
        """Тест валидации: разные торговые пары должны вызвать ошибку"""
        from exchanges.models import TradingPair
        from candle_sources.models import CandleSource

        data = create_exchange_candles

        # Создаем другую торговую пару
        other_pair = TradingPair.objects.create(
            name="ETH/USDT",
            symbol="ETH/USDT",
            min_amount=Decimal("0.01"),
            max_amount=Decimal("1000"),
            fee_percent=Decimal("0.1"),
        )

        source3 = CandleSource.objects.create(
            exchange_client=data["source2"].exchange_client,
            trading_pair=other_pair,
            timeframe=Timeframe.ONE_HOUR.value,
        )

        with pytest.raises(ValueError, match="same trading pair"):
            DivisionCandleProvider(data["source1"], source3)

    def test_get_candle_division_calculation(self, create_exchange_candles):
        """Тест правильности расчета деления"""
        data = create_exchange_candles

        provider = DivisionCandleProvider(data["source1"], data["source2"])

        candle1_domain = data["candles1"][0].instantiate()
        candle2_domain = data["candles2"][0].instantiate()

        candle = provider.get_candle(candle1_domain, candle2_domain)

        # Проверяем деление используя фактические значения из БД
        # candles1[0]: open=50000, high=50100, low=40900, close=50050
        # candles2[0]: open=40000, high=40100, low=30900, close=40050
        expected_open = candle1_domain.open / candle2_domain.open
        assert abs(candle.open - expected_open) < Decimal("0.0001")

        expected_high = candle1_domain.high / candle2_domain.high
        assert abs(candle.high - expected_high) < Decimal("0.0001")

        expected_low = candle1_domain.low / candle2_domain.low
        assert abs(candle.low - expected_low) < Decimal("0.0001")

        expected_close = candle1_domain.close / candle2_domain.close
        assert abs(candle.close - expected_close) < Decimal("0.0001")

    def test_get_candle_volume_is_minimum(self, create_exchange_candles):
        """Тест что volume берется минимальный из двух источников"""
        data = create_exchange_candles

        provider = DivisionCandleProvider(data["source1"], data["source2"])

        candle = provider.get_candle(
            data["candles1"][0].instantiate(),
            data["candles2"][0].instantiate(),
        )

        # volume должен быть min(100, 90) = 90
        assert candle.volume == Decimal("90")

    def test_get_candle_returns_provider_candle_with_two_sources(
        self, create_exchange_candles
    ):
        """Тест что get_candle возвращает ProviderCandle с двумя источниками"""
        data = create_exchange_candles

        provider = DivisionCandleProvider(data["source1"], data["source2"])

        candle = provider.get_candle(
            data["candles1"][0].instantiate(),
            data["candles2"][0].instantiate(),
        )

        assert isinstance(candle, ProviderCandle)
        assert candle.first_candle is not None
        assert candle.second_candle is not None
        assert candle.first_candle.id == data["candles1"][0].id
        assert candle.second_candle.id == data["candles2"][0].id

    def test_get_candles_returns_synthetic_candles(self, create_exchange_candles):
        """Тест получения списка синтетических свечей"""
        data = create_exchange_candles

        provider = DivisionCandleProvider(data["source1"], data["source2"])

        start = data["base_time"]
        end = data["base_time"] + timedelta(hours=4)

        candles = provider.get_candles(start, end)

        assert len(candles) == 5
        assert all(isinstance(c, ProviderCandle) for c in candles)
        assert all(c.first_candle is not None for c in candles)
        assert all(c.second_candle is not None for c in candles)

    def test_get_candles_pairs_correctly(self, create_exchange_candles):
        """Тест что свечи правильно спариваются по timestamp"""
        data = create_exchange_candles

        provider = DivisionCandleProvider(data["source1"], data["source2"])

        start = data["base_time"]
        end = data["base_time"] + timedelta(hours=2)

        candles = provider.get_candles(start, end)

        # Проверяем что каждая синтетическая свеча создана из свечей с одинаковым timestamp
        for candle in candles:
            assert candle.first_candle.timestamp == candle.second_candle.timestamp

    def test_get_last_candles_returns_synthetic_candles(self, create_exchange_candles):
        """Тест получения последних синтетических свечей"""
        data = create_exchange_candles

        provider = DivisionCandleProvider(data["source1"], data["source2"])

        candles = provider.get_last_candles(3)

        assert len(candles) == 3
        assert all(isinstance(c, ProviderCandle) for c in candles)
        assert all(c.first_candle is not None for c in candles)
        assert all(c.second_candle is not None for c in candles)

    def test_get_candle_iterator_yields_synthetic_candles(
        self, create_exchange_candles
    ):
        """Тест генератора синтетических свечей"""
        data = create_exchange_candles

        provider = DivisionCandleProvider(data["source1"], data["source2"])

        start = data["base_time"]
        end = data["base_time"] + timedelta(hours=9)

        candles = list(provider.get_candle_iterator(start, end))

        assert len(candles) == 10
        assert all(isinstance(c, ProviderCandle) for c in candles)
        assert all(c.first_candle is not None for c in candles)
        assert all(c.second_candle is not None for c in candles)

    def test_get_candle_iterator_is_memory_efficient(self, create_exchange_candles):
        """Тест что итератор работает эффективно с памятью"""
        data = create_exchange_candles

        provider = DivisionCandleProvider(data["source1"], data["source2"])

        start = data["base_time"]
        end = data["base_time"] + timedelta(hours=9)

        iterator = provider.get_candle_iterator(start, end)
        assert hasattr(iterator, "__iter__")
        assert hasattr(iterator, "__next__")


@pytest.mark.django_db
class TestMinusCandleProvider:
    """Тесты для MinusCandleProvider"""

    def test_provider_initialization(self, create_exchange_candles):
        """Тест инициализации провайдера"""
        data = create_exchange_candles

        provider = MinusCandleProvider(data["source1"], data["source2"])

        assert isinstance(provider.source_1, CandleSource)
        assert isinstance(provider.source_2, CandleSource)
        assert provider.source_1.pk == data["source1"].id
        assert provider.source_2.pk == data["source2"].id

    def test_validation_different_timeframes_raises_error(
        self, create_exchange_candles
    ):
        """Тест валидации: разные таймфреймы должны вызвать ошибку"""
        from candle_sources.models import CandleSource

        data = create_exchange_candles

        source3 = CandleSource.objects.create(
            exchange_client=data["source2"].exchange_client,
            trading_pair=data["trading_pair"],
            timeframe=Timeframe.FOUR_HOURS.value,
        )

        with pytest.raises(ValueError, match="same timeframe"):
            MinusCandleProvider(data["source1"], source3)

    def test_validation_different_trading_pairs_raises_error(
        self, create_exchange_candles
    ):
        """Тест валидации: разные торговые пары должны вызвать ошибку"""
        from exchanges.models import TradingPair
        from candle_sources.models import CandleSource

        data = create_exchange_candles

        other_pair = TradingPair.objects.create(
            name="ETH/USDT",
            symbol="ETH/USDT",
            min_amount=Decimal("0.01"),
            max_amount=Decimal("1000"),
            fee_percent=Decimal("0.1"),
        )

        source3 = CandleSource.objects.create(
            exchange_client=data["source2"].exchange_client,
            trading_pair=other_pair,
            timeframe=Timeframe.ONE_HOUR.value,
        )

        with pytest.raises(ValueError, match="same trading pair"):
            MinusCandleProvider(data["source1"], source3)

    def test_get_candle_subtraction_calculation(self, create_exchange_candles):
        """Тест правильности расчета вычитания"""
        data = create_exchange_candles

        provider = MinusCandleProvider(data["source1"], data["source2"])

        candle = provider.get_candle(
            data["candles1"][0].instantiate(),
            data["candles2"][0].instantiate(),
        )

        # Проверяем вычитание: 50000 - 40000 = 10000
        expected_open = Decimal("50000") - Decimal("40000")
        assert candle.open == expected_open

        # Проверяем вычитание для всех OHLC
        expected_high = Decimal("50100") - Decimal("40100")
        assert candle.high == expected_high

        expected_low = Decimal("49900") - Decimal("39900")
        assert candle.low == expected_low

        expected_close = Decimal("50050") - Decimal("40050")
        assert candle.close == expected_close

    def test_get_candle_volume_is_minimum(self, create_exchange_candles):
        """Тест что volume берется минимальный из двух источников"""
        data = create_exchange_candles

        provider = MinusCandleProvider(data["source1"], data["source2"])

        candle = provider.get_candle(
            data["candles1"][0].instantiate(),
            data["candles2"][0].instantiate(),
        )

        assert candle.volume == Decimal("90")

    def test_get_candle_returns_provider_candle_with_two_sources(
        self, create_exchange_candles
    ):
        """Тест что get_candle возвращает ProviderCandle с двумя источниками"""
        data = create_exchange_candles

        provider = MinusCandleProvider(data["source1"], data["source2"])

        candle = provider.get_candle(
            data["candles1"][0].instantiate(),
            data["candles2"][0].instantiate(),
        )

        assert isinstance(candle, ProviderCandle)
        assert candle.first_candle is not None
        assert candle.second_candle is not None
        assert candle.first_candle.id == data["candles1"][0].id
        assert candle.second_candle.id == data["candles2"][0].id

    def test_get_candles_returns_synthetic_candles(self, create_exchange_candles):
        """Тест получения списка синтетических свечей"""
        data = create_exchange_candles

        provider = MinusCandleProvider(data["source1"], data["source2"])

        start = data["base_time"]
        end = data["base_time"] + timedelta(hours=4)

        candles = provider.get_candles(start, end)

        assert len(candles) == 5
        assert all(isinstance(c, ProviderCandle) for c in candles)
        assert all(c.first_candle is not None for c in candles)
        assert all(c.second_candle is not None for c in candles)

    def test_get_last_candles_returns_synthetic_candles(self, create_exchange_candles):
        """Тест получения последних синтетических свечей"""
        data = create_exchange_candles

        provider = MinusCandleProvider(data["source1"], data["source2"])

        candles = provider.get_last_candles(3)

        assert len(candles) == 3
        assert all(isinstance(c, ProviderCandle) for c in candles)

    def test_get_candle_iterator_yields_synthetic_candles(
        self, create_exchange_candles
    ):
        """Тест генератора синтетических свечей"""
        data = create_exchange_candles

        provider = MinusCandleProvider(data["source1"], data["source2"])

        start = data["base_time"]
        end = data["base_time"] + timedelta(hours=9)

        candles = list(provider.get_candle_iterator(start, end))

        assert len(candles) == 10
        assert all(isinstance(c, ProviderCandle) for c in candles)
        assert all(c.first_candle is not None for c in candles)
        assert all(c.second_candle is not None for c in candles)


@pytest.mark.django_db
class TestCandleProviderORM:
    """Тесты для ORM модели CandleProvider"""

    def test_create_plain_provider(self, create_exchange_candles):
        """Тест создания plain провайдера"""
        from candle_providers.models import CandleProvider

        data = create_exchange_candles

        provider = CandleProvider.objects.create(
            class_name="PlainCandleProvider",
            first_source=data["source1"],
        )

        assert provider.class_name == "PlainCandleProvider"
        assert provider.timeframe == "1h"
        assert provider.trading_pair == data["trading_pair"]

    def test_create_division_provider(self, create_exchange_candles):
        """Тест создания division провайдера"""
        from candle_providers.models import CandleProvider

        data = create_exchange_candles

        provider = CandleProvider.objects.create(
            class_name="DivisionCandleProvider",
            first_source=data["source1"],
            second_source=data["source2"],
        )

        assert provider.class_name == "DivisionCandleProvider"
        assert provider.first_source == data["source1"]
        assert provider.second_source == data["source2"]

    def test_create_minus_provider(self, create_exchange_candles):
        """Тест создания minus провайдера"""
        from candle_providers.models import CandleProvider

        data = create_exchange_candles

        provider = CandleProvider.objects.create(
            class_name="MinusCandleProvider",
            first_source=data["source1"],
            second_source=data["source2"],
        )

        assert provider.class_name == "MinusCandleProvider"

    def test_validation_plain_should_not_have_second(self, create_exchange_candles):
        """Тест валидации: PlainCandleProvider не должен иметь second_source"""
        from candle_providers.models import CandleProvider
        from django.core.exceptions import ValidationError

        data = create_exchange_candles

        provider = CandleProvider(
            class_name="PlainCandleProvider",
            first_source=data["source1"],
            second_source=data["source2"],  # Не должно быть!
        )

        with pytest.raises(
            ValidationError, match="не должен иметь вторичный источник"
        ):
            provider.full_clean()

    def test_validation_synthetic_requires_second(self, create_exchange_candles):
        """Тест валидации: синтетические провайдеры требуют second_source"""
        from candle_providers.models import CandleProvider
        from django.core.exceptions import ValidationError

        data = create_exchange_candles

        provider = CandleProvider(
            class_name="DivisionCandleProvider",
            first_source=data["source1"],
            # Нет second_source!
        )

        with pytest.raises(ValidationError, match="требуют second_source"):
            provider.full_clean()

    def test_validation_same_timeframe_required(self, create_exchange_candles):
        """Тест валидации: источники должны иметь одинаковый таймфрейм"""
        from candle_providers.models import CandleProvider
        from candle_sources.models import CandleSource
        from django.core.exceptions import ValidationError

        data = create_exchange_candles

        source3 = CandleSource.objects.create(
            exchange_client=data["source2"].exchange_client,
            trading_pair=data["trading_pair"],
            timeframe=Timeframe.FOUR_HOURS.value,
        )

        provider = CandleProvider(
            class_name="DivisionCandleProvider",
            first_source=data["source1"],
            second_source=source3,
        )

        with pytest.raises(ValidationError, match="одинаковый таймфрейм"):
            provider.full_clean()

    def test_validation_same_trading_pair_required(self, create_exchange_candles):
        """Тест валидации: источники должны иметь одинаковую торговую пару"""
        from candle_providers.models import CandleProvider
        from candle_sources.models import CandleSource
        from exchanges.models import TradingPair
        from django.core.exceptions import ValidationError

        data = create_exchange_candles

        other_pair = TradingPair.objects.create(
            name="ETH/USDT",
            symbol="ETH/USDT",
            min_amount=Decimal("0.01"),
            max_amount=Decimal("1000"),
            fee_percent=Decimal("0.1"),
        )

        source3 = CandleSource.objects.create(
            exchange_client=data["source2"].exchange_client,
            trading_pair=other_pair,
            timeframe=Timeframe.ONE_HOUR.value,
        )

        provider = CandleProvider(
            class_name="DivisionCandleProvider",
            first_source=data["source1"],
            second_source=source3,
        )

        with pytest.raises(ValidationError, match="одинаковую торговую пару"):
            provider.full_clean()

    def test_validation_different_exchanges_required(self, create_exchange_candles):
        """Тест валидации: источники должны быть с разных бирж"""
        from candle_providers.models import CandleProvider
        from django.core.exceptions import ValidationError

        data = create_exchange_candles

        # Используем один и тот же источник дважды - это та же биржа
        provider = CandleProvider(
            class_name="DivisionCandleProvider",
            first_source=data["source1"],
            second_source=data["source1"],  # Тот же источник = та же биржа
        )

        with pytest.raises(ValidationError, match="разных бирж"):
            provider.full_clean()

    def test_instantiate_plain_provider(self, create_exchange_candles):
        """Тест instantiate() для plain провайдера"""
        from candle_providers.models import CandleProvider

        data = create_exchange_candles

        provider_orm = CandleProvider.objects.create(
            class_name="PlainCandleProvider",
            first_source=data["source1"],
        )

        provider_domain = provider_orm.instantiate()

        assert isinstance(provider_domain, PlainCandleProvider)
        assert provider_domain.source_id == data["source1"].id

    def test_instantiate_division_provider(self, create_exchange_candles):
        """Тест instantiate() для division провайдера"""
        from candle_providers.models import CandleProvider

        data = create_exchange_candles

        provider_orm = CandleProvider.objects.create(
            class_name="DivisionCandleProvider",
            first_source=data["source1"],
            second_source=data["source2"],
        )

        provider_domain = provider_orm.instantiate()

        assert isinstance(provider_domain, DivisionCandleProvider)
        assert provider_domain.source_1.pk == data["source1"].id
        assert provider_domain.source_2.pk == data["source2"].id

    def test_instantiate_minus_provider(self, create_exchange_candles):
        """Тест instantiate() для minus провайдера"""
        from candle_providers.models import CandleProvider

        data = create_exchange_candles

        provider_orm = CandleProvider.objects.create(
            class_name="MinusCandleProvider",
            first_source=data["source1"],
            second_source=data["source2"],
        )

        provider_domain = provider_orm.instantiate()

        assert isinstance(provider_domain, MinusCandleProvider)

    def test_str_representation_plain(self, create_exchange_candles):
        """Тест строкового представления для plain провайдера"""
        from candle_providers.models import CandleProvider

        data = create_exchange_candles

        provider = CandleProvider.objects.create(
            class_name="PlainCandleProvider",
            first_source=data["source1"],
        )

        expected = f"PlainCandleProvider ({data['source1']})"
        assert str(provider) == expected

    def test_str_representation_synthetic(self, create_exchange_candles):
        """Тест строкового представления для синтетического провайдера"""
        from candle_providers.models import CandleProvider

        data = create_exchange_candles

        provider = CandleProvider.objects.create(
            class_name="DivisionCandleProvider",
            first_source=data["source1"],
            second_source=data["source2"],
        )

        expected = (
            f"DivisionCandleProvider ({data['source1']} + {data['source2']})"
        )
        assert str(provider) == expected

    def test_get_class_method(self, create_exchange_candles):
        """Тест метода get_class()"""
        from candle_providers.models import CandleProvider

        data = create_exchange_candles

        provider = CandleProvider.objects.create(
            class_name="PlainCandleProvider",
            first_source=data["source1"],
        )

        cls = provider.get_class()
        assert cls == PlainCandleProvider

    def test_timeframe_property(self, create_exchange_candles):
        """Тест свойства timeframe"""
        from candle_providers.models import CandleProvider

        data = create_exchange_candles

        provider = CandleProvider.objects.create(
            class_name="PlainCandleProvider",
            first_source=data["source1"],
        )

        assert provider.timeframe == data["source1"].timeframe

    def test_trading_pair_property(self, create_exchange_candles):
        """Тест свойства trading_pair"""
        from candle_providers.models import CandleProvider

        data = create_exchange_candles

        provider = CandleProvider.objects.create(
            class_name="PlainCandleProvider",
            first_source=data["source1"],
        )

        assert provider.trading_pair == data["source1"].trading_pair
