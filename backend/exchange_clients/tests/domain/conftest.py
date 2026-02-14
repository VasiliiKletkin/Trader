"""
Shared fixtures for exchange_clients domain tests.
"""

from unittest.mock import AsyncMock, Mock

import pytest

from exchange_clients.domain import ExchangeClientProxy, OrderSide, OrderStatus

# ==================== Mock CCXT Exchange ====================


@pytest.fixture
def mock_ccxt_exchange():
    """Mock ccxt exchange для тестирования."""
    exchange = Mock()
    exchange.timeout = 10000
    exchange.close = AsyncMock()
    exchange.fetch_ohlcv = AsyncMock()
    exchange.fetch_balance = AsyncMock()
    exchange.fetch_orders = AsyncMock()
    exchange.fetch_open_orders = AsyncMock()
    exchange.create_market_order = AsyncMock()
    exchange.fetch_open_order = AsyncMock()
    exchange.cancel_all_orders = AsyncMock()
    exchange.enable_demo_trading = Mock()
    return exchange


# ==================== Exchange Client Proxy ====================


@pytest.fixture
def exchange_client_proxy():
    """Фикстура для прокси."""
    return ExchangeClientProxy(
        protocol="socks5",
        host="proxy.example.com",
        port="1080",
        username="user",
        password="pass",
    )


# ==================== Sample Data ====================


@pytest.fixture
def sample_ohlcv_data():
    """Пример данных OHLCV от CCXT."""
    return [
        [1609459200000, 29000.0, 29500.0, 28800.0, 29200.0, 1500.0],
        [1609462800000, 29200.0, 29600.0, 29100.0, 29400.0, 1600.0],
        [1609466400000, 29400.0, 29800.0, 29300.0, 29700.0, 1700.0],
    ]


@pytest.fixture
def sample_balance_data():
    """Пример данных баланса от CCXT."""
    return {
        "BTC": {
            "free": 1.5,
            "used": 0.5,
            "total": 2.0,
            "debt": 0.0,
        },
        "USDT": {
            "free": 10000.0,
            "used": 2000.0,
            "total": 12000.0,
            "debt": 0.0,
        },
        "info": {"some": "data"},  # Игнорируется при парсинге
        "timestamp": 1609459200000,  # Игнорируется при парсинге
    }


@pytest.fixture
def sample_order_data():
    """Пример данных ордера от CCXT."""
    return {
        "id": "order_123",
        "timestamp": 1609459200000,
        "side": OrderSide.BUY.value,
        "price": 29000.0,
        "average": 29000.0,
        "amount": 0.1,
        "cost": 2900.0,
        "status": OrderStatus.CLOSED.value,
        "fee": {"cost": 2.9},
    }
