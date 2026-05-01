"""
Тесты для Celery задач оптимизаторов с проверкой количества SQL-запросов.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from candle_sources.models import CandleSource
from exchange_clients.models import ExchangeClient
from exchanges.domain import BybitExchange
from exchanges.models import Exchange, ExchangeTradingPair
from traders.domain.risk_managers import (
    SLPercentTPPercentPSAllInRiskManager,
)
from traders.domain.strategies import (
    MoneyFlowIndexStrategy,
)
from traders.models import (
    TraderOptimizationAlgorithm,
    TraderOptimizer,
)
from traders.tasks import optimizer_optimize


@pytest.fixture
def mock_optimizer_optimize():
    """Mock метода optimize() на модели TraderOptimizer."""
    with patch.object(TraderOptimizer, "optimize", return_value=None) as mock:
        yield mock


@pytest.fixture
def optimizer_test_data(db):
    """Создает тестовые данные для оптимизатора."""
    exchange, _ = Exchange.objects.get_or_create(
        class_name=BybitExchange.__name__,
        defaults={"name": "Test Exchange"},
    )
    trading_pair, _ = ExchangeTradingPair.objects.get_or_create(
        exchange=exchange,
        name="BTC/USDT",
        type="futures",
        defaults={
            "base_currency": "BTC",
            "quote_currency": "USDT",
            "settle_currency": "USDT",
            "is_linear": True,
            "symbol": "BTC/USDT:USDT",
        },
    )
    exchange_client = ExchangeClient.objects.create(
        exchange=exchange,
        name="Test Client",
        arguments={"api_key": "test_key", "api_secret": "test_secret"},
    )
    candle_source = CandleSource.objects.create(
        trading_pair=trading_pair,
        timeframe="1h",
    )
    algorithm = TraderOptimizationAlgorithm.objects.create(
        name="Test Optuna",
        class_name="OptunaOptimizationAlgorithm",
        arguments={"n_trials": 10},
    )
    return {
        "exchange": exchange,
        "trading_pair": trading_pair,
        "exchange_client": exchange_client,
        "candle_source": candle_source,
        "algorithm": algorithm,
    }


@pytest.mark.django_db
class TestOptimizerOptimize:
    """Тесты для задачи optimizer_optimize."""

    def test_optimizer_optimize_calls_optimize_method(
        self, mock_optimizer_optimize, optimizer_test_data
    ):
        """Тест вызывает метод optimize() на модели оптимизатора."""
        optimizer = TraderOptimizer.objects.create(
            algorithm=optimizer_test_data["algorithm"],
            candle_source=optimizer_test_data["candle_source"],
            strategy_class_name=MoneyFlowIndexStrategy.__name__,
            risk_manager_class_name=SLPercentTPPercentPSAllInRiskManager.__name__,
            initial_balance=Decimal("1000"),
            max_positions_count=1,
        )

        optimizer_optimize(optimizer_id=optimizer.pk)

        mock_optimizer_optimize.assert_called_once()

    def test_optimizer_optimize_query_count(
        self, mock_optimizer_optimize, optimizer_test_data
    ):
        """Тест проверяет количество SQL-запросов при вызове задачи."""
        optimizer = TraderOptimizer.objects.create(
            algorithm=optimizer_test_data["algorithm"],
            candle_source=optimizer_test_data["candle_source"],
            strategy_class_name=MoneyFlowIndexStrategy.__name__,
            risk_manager_class_name=SLPercentTPPercentPSAllInRiskManager.__name__,
            initial_balance=Decimal("1000"),
            max_positions_count=1,
        )

        with CaptureQueriesContext(connection) as queries:
            optimizer_optimize(optimizer_id=optimizer.pk)

        # Ожидаем: 1 запрос для получения оптимизатора
        assert len(queries) == 1
