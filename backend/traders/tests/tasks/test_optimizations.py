"""
Тесты для Celery задач оптимизаторов с проверкой количества SQL-запросов.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from candle_sources.models import CandleSource
from exchange_clients.models import ExchangeClient
from exchanges.models import Exchange, TradingPair
from traders.domain.risk_managers import (
    SLPercentTPPercentPSAllInRiskManager,
)
from traders.domain.strategies import (
    MoneyFlowIndexStrategy,
)
from traders.models import (
    TraderOptimizationAlgorithm,
    TraderOptimizationResult,
    TraderOptimizer,
)
from traders.schemas import OptimizerStatus
from traders.tasks import optimize_old_optimizers, optimizer_optimize


@pytest.fixture
def mock_optimizer_optimize():
    """Mock метода optimize() на модели TraderOptimizer."""
    with patch.object(TraderOptimizer, "optimize", return_value=None) as mock:
        yield mock


@pytest.fixture
def optimizer_test_data(db):
    """Создает тестовые данные для оптимизатора."""
    exchange, _ = Exchange.objects.get_or_create(
        class_name="ByBitExchangeClient",
        defaults={"name": "Test Exchange"},
    )
    trading_pair, _ = TradingPair.objects.get_or_create(
        name="BTC/USDT",
        defaults={
            "symbol": "BTC/USDT:USDT",
            "min_amount": Decimal("0.001"),
            "max_amount": Decimal("1000"),
            "fee_percent": Decimal("0.1"),
        },
    )
    exchange_client = ExchangeClient.objects.create(
        exchange=exchange,
        name="Test Client",
        arguments={"api_key": "test_key", "api_secret": "test_secret"},
    )
    candle_source = CandleSource.objects.create(
        exchange_client=exchange_client,
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
            exchange=optimizer_test_data["exchange"],
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
            exchange=optimizer_test_data["exchange"],
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


@pytest.mark.django_db
class TestOptimizeOldOptimizers:
    """Тесты для задачи optimize_old_optimizers."""

    def test_optimize_old_optimizers_skips_when_active_optimization(
        self, mock_optimizer_optimize, optimizer_test_data
    ):
        """Тест пропускает запуск если есть активная оптимизация."""
        TraderOptimizer.objects.create(
            algorithm=optimizer_test_data["algorithm"],
            exchange=optimizer_test_data["exchange"],
            candle_source=optimizer_test_data["candle_source"],
            strategy_class_name=MoneyFlowIndexStrategy.__name__,
            risk_manager_class_name=SLPercentTPPercentPSAllInRiskManager.__name__,
            initial_balance=Decimal("1000"),
            max_positions_count=1,
            status=OptimizerStatus.REBOOTING,
        )

        with CaptureQueriesContext(connection) as queries:
            optimize_old_optimizers()

        assert len(queries) == 1
        mock_optimizer_optimize.assert_not_called()

    def test_optimize_old_optimizers_selects_oldest_result(
        self, mock_optimizer_optimize, optimizer_test_data
    ):
        """Тест выбирает оптимизатор с самым старым результатом."""
        # Создаем оптимизатор с новым результатом
        optimizer_new = TraderOptimizer.objects.create(
            algorithm=optimizer_test_data["algorithm"],
            exchange=optimizer_test_data["exchange"],
            candle_source=optimizer_test_data["candle_source"],
            strategy_class_name=MoneyFlowIndexStrategy.__name__,
            risk_manager_class_name=SLPercentTPPercentPSAllInRiskManager.__name__,
            initial_balance=Decimal("1000"),
            max_positions_count=1,
            status=OptimizerStatus.ENABLED,
        )
        TraderOptimizationResult.objects.create(
            optimizer=optimizer_new,
            pnl=Decimal("100"),
            win_rate=Decimal("0.6"),
            avg_candles_per_position=Decimal("10"),
            pnl_r2=Decimal("0.8"),
            roi=Decimal("0.1"),
            sharpe=Decimal("1.5"),
            total_positions=10,
            strategy_arguments={"period": 14},
            risk_manager_arguments={"stop_loss_percent": 2.0},
            duration=timezone.timedelta(minutes=30),
            created_at=timezone.now(),
        )

        # Создаем оптимизатор со старым результатом
        optimizer_old = TraderOptimizer.objects.create(
            algorithm=optimizer_test_data["algorithm"],
            exchange=optimizer_test_data["exchange"],
            candle_source=optimizer_test_data["candle_source"],
            strategy_class_name="StochasticStrategy",
            risk_manager_class_name="SLPercentTPPercentPSAllInRiskManager",
            initial_balance=Decimal("1000"),
            max_positions_count=1,
            status=OptimizerStatus.ENABLED,
        )
        TraderOptimizationResult.objects.create(
            optimizer=optimizer_old,
            pnl=Decimal("50"),
            win_rate=Decimal("0.5"),
            avg_candles_per_position=Decimal("12"),
            pnl_r2=Decimal("0.7"),
            roi=Decimal("0.05"),
            sharpe=Decimal("1.0"),
            total_positions=5,
            strategy_arguments={"period": 10},
            risk_manager_arguments={"stop_loss_percent": 1.5},
            duration=timezone.timedelta(minutes=20),
            created_at=timezone.now() - timezone.timedelta(days=10),
        )

        with (
            patch("traders.tasks.optimizer_optimize.delay") as mock_delay,
            CaptureQueriesContext(connection) as queries,
        ):
            optimize_old_optimizers()

        assert len(queries) == 2
        mock_delay.assert_called_once_with(optimizer_old.pk)

    def test_optimize_old_optimizers_no_results(
        self, mock_optimizer_optimize, optimizer_test_data
    ):
        """Тест когда нет оптимизаторов с результатами."""
        TraderOptimizer.objects.create(
            algorithm=optimizer_test_data["algorithm"],
            exchange=optimizer_test_data["exchange"],
            candle_source=optimizer_test_data["candle_source"],
            strategy_class_name=MoneyFlowIndexStrategy.__name__,
            risk_manager_class_name=SLPercentTPPercentPSAllInRiskManager.__name__,
            initial_balance=Decimal("1000"),
            max_positions_count=1,
            status=OptimizerStatus.ENABLED,
        )

        with (
            patch("traders.tasks.optimizer_optimize.delay") as mock_delay,
            CaptureQueriesContext(connection) as queries,
        ):
            optimize_old_optimizers()

        assert len(queries) == 2
        mock_delay.assert_not_called()

    def test_optimize_old_optimizers_query_count(self, mock_optimizer_optimize):
        """Тест проверяет количество запросов."""
        with CaptureQueriesContext(connection) as queries:
            optimize_old_optimizers()

        assert len(queries) == 2
