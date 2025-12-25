"""Фикстуры для тестов доменной модели candle_providers."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from candle_sources.models import CandleSource
from exchange_clients.models import ExchangeClient
from exchanges.models import Exchange, ExchangeTradingPair, TradingPair, ExchangeCandle
from exchanges.domain import Timeframe


@pytest.fixture
def exchange_binance(db) -> Exchange:
    """Фикстура для биржи Binance."""
    return Exchange.objects.create(name="Binance", class_name="BinanceClient")


@pytest.fixture
def exchange_bybit(db) -> Exchange:
    """Фикстура для биржи ByBit."""
    return Exchange.objects.create(name="ByBit", class_name="BybitClient")


@pytest.fixture
def trading_pair_btc_usdt(db) -> TradingPair:
    """Фикстура для торговой пары BTC/USDT."""
    return TradingPair.objects.create(
        name="BTC/USDT",
        symbol="BTC/USDT",
        min_amount=Decimal("0.001"),
        max_amount=Decimal("1000"),
        fee_percent=Decimal("0.1"),
    )


@pytest.fixture
def trading_pair_eth_usdt(db) -> TradingPair:
    """Фикстура для торговой пары ETH/USDT (для тестов валидации)."""
    return TradingPair.objects.create(
        name="ETH/USDT",
        symbol="ETH/USDT",
        min_amount=Decimal("0.01"),
        max_amount=Decimal("1000"),
        fee_percent=Decimal("0.1"),
    )


@pytest.fixture
def exchange_client_binance(db, exchange_binance) -> ExchangeClient:
    """Фикстура для клиента Binance."""
    return ExchangeClient.objects.create(
        exchange=exchange_binance,
        api_key="test_key_1",
        api_secret="test_secret_1",
        name="Test Client 1",
    )


@pytest.fixture
def exchange_client_bybit(db, exchange_bybit) -> ExchangeClient:
    """Фикстура для клиента ByBit."""
    return ExchangeClient.objects.create(
        exchange=exchange_bybit,
        api_key="test_key_2",
        api_secret="test_secret_2",
        name="Test Client 2",
    )


@pytest.fixture
def candle_source_binance(
    db, exchange_client_binance, trading_pair_btc_usdt
) -> CandleSource:
    """Фикстура для источника свечей Binance (1h)."""
    return CandleSource.objects.create(
        exchange_client=exchange_client_binance,
        trading_pair=trading_pair_btc_usdt,
        timeframe=Timeframe.ONE_HOUR.value,
    )


@pytest.fixture
def candle_source_bybit(
    db, exchange_client_bybit, trading_pair_btc_usdt
) -> CandleSource:
    """Фикстура для источника свечей ByBit (1h)."""
    return CandleSource.objects.create(
        exchange_client=exchange_client_bybit,
        trading_pair=trading_pair_btc_usdt,
        timeframe=Timeframe.ONE_HOUR.value,
    )


@pytest.fixture
def candle_source_4h(
    db, exchange_client_bybit, trading_pair_btc_usdt
) -> CandleSource:
    """Фикстура для источника свечей ByBit (4h) - для тестов валидации таймфреймов."""
    return CandleSource.objects.create(
        exchange_client=exchange_client_bybit,
        trading_pair=trading_pair_btc_usdt,
        timeframe=Timeframe.FOUR_HOURS.value,
    )


@pytest.fixture
def candle_source_eth(
    db, exchange_client_bybit, trading_pair_eth_usdt
) -> CandleSource:
    """Фикстура для источника свечей ETH/USDT - для тестов валидации торговых пар."""
    return CandleSource.objects.create(
        exchange_client=exchange_client_bybit,
        trading_pair=trading_pair_eth_usdt,
        timeframe=Timeframe.ONE_HOUR.value,
    )


@pytest.fixture
def base_time() -> datetime:
    """Базовое время для создания свечей."""
    return datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def create_exchange_candles(
    db,
    candle_source_binance,
    candle_source_bybit,
    trading_pair_btc_usdt,
    base_time,
):
    """
    Фикстура для создания тестовых свечей в БД.

    Создает 10 свечей для каждого источника (Binance и ByBit) с часовым интервалом.
    Цены на Binance выше (50000-59050), на ByBit ниже (40000-49050).

    Returns:
        dict: Словарь с ключами:
            - source1: CandleSource (Binance)
            - source2: CandleSource (ByBit)
            - candles1: list[ExchangeCandle] (10 свечей Binance)
            - candles2: list[ExchangeCandle] (10 свечей ByBit)
            - base_time: datetime (базовое время первой свечи)
            - trading_pair: TradingPair (BTC/USDT)
    """
    candles_source1 = []
    candles_source2 = []

    for i in range(10):
        timestamp = base_time + timedelta(hours=i)

        # Свечи для Binance (цены выше)
        c1 = ExchangeCandle.objects.create(
            exchange=candle_source_binance.exchange_client.exchange,
            timeframe=candle_source_binance.timeframe,
            trading_pair=candle_source_binance.trading_pair,
            timestamp=timestamp,
            open=Decimal(f"5{i}000"),
            high=Decimal(f"5{i}100"),
            low=Decimal(f"4{i}900"),
            close=Decimal(f"5{i}050"),
            volume=Decimal("100"),
        )
        candles_source1.append(c1)

        # Свечи для ByBit (цены ниже)
        c2 = ExchangeCandle.objects.create(
            exchange=candle_source_bybit.exchange_client.exchange,
            timeframe=candle_source_bybit.timeframe,
            trading_pair=candle_source_bybit.trading_pair,
            timestamp=timestamp,
            open=Decimal(f"4{i}000"),
            high=Decimal(f"4{i}100"),
            low=Decimal(f"3{i}900"),
            close=Decimal(f"4{i}050"),
            volume=Decimal("90"),
        )
        candles_source2.append(c2)

    return {
        "source1": candle_source_binance,
        "source2": candle_source_bybit,
        "candles1": candles_source1,
        "candles2": candles_source2,
        "base_time": base_time,
        "trading_pair": trading_pair_btc_usdt,
    }
