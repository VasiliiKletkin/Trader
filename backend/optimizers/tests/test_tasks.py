"""
Тесты для Celery задач оптимизаторов с проверкой количества SQL-запросов.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest
from core.utils.types import OptimizerStatus
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from optimizers.models import TraderOptimizer, TraderOptimizationAlgorithm
from optimizers.tasks import optimizer_optimize, optimize_old_optimizers


@pytest.fixture
def mock_optimizer_optimize():
    """Mock метода optimize() на модели TraderOptimizer."""
    with patch.object(
        TraderOptimizer, "optimize", return_value=None
    ) as mock:
        yield mock


@pytest.mark.django_db
class TestOptimizerOptimize:
    """Тесты для задачи optimizer_optimize."""

    def test_optimizer_optimize_calls_optimize_method(
        self, mock_optimizer_optimize, db
    ):
        """Тест вызывает метод optimize() на модели оптимизатора."""
        # Arrange: создаем тестовый оптимизатор
        from candle_providers.models import CandleProvider
        from candle_sources.models import CandleSource
        from exchange_clients.models import ExchangeClient
        from exchanges.models import Exchange, TradingPair

        exchange = Exchange.objects.create(
            name="Test Exchange", class_name="ByBitExchangeClient"
        )
        trading_pair = TradingPair.objects.create(
            name="BTC/USDT",
            symbol="BTC/USDT:USDT",
            min_amount=Decimal("0.001"),
            max_amount=Decimal("1000"),
            fee_percent=Decimal("0.1"),
        )
        exchange_client = ExchangeClient.objects.create(
            exchange=exchange,
            api_key="test_key",
            api_secret="test_secret",
            name="Test Client",
        )
        candle_source = CandleSource.objects.create(
            exchange_client=exchange_client,
            trading_pair=trading_pair,
            timeframe="1h",
        )
        candle_provider = CandleProvider.objects.create(
            class_name="PlainCandleProvider",
            primary_source=candle_source,
        )
        algorithm = TraderOptimizationAlgorithm.objects.create(
            name="Test Optuna",
            class_name="OptunaOptimizationAlgorithm",
            arguments={"n_trials": 10},
        )
        optimizer = TraderOptimizer.objects.create(
            algorithm=algorithm,
            exchange=exchange,
            candle_provider=candle_provider,
            strategy_class_name="MoneyFlowIndexStrategy",
            risk_manager_class_name="SLPercentTPPercentPSAllInRiskManager",
            initial_balance=Decimal("1000"),
            max_positions_count=1,
        )

        # Act: вызываем задачу
        optimizer_optimize(optimizer_id=optimizer.pk)

        # Assert: проверяем что optimize() был вызван
        mock_optimizer_optimize.assert_called_once()

    def test_optimizer_optimize_query_count(self, mock_optimizer_optimize, db):
        """Тест проверяет количество SQL-запросов при вызове задачи."""
        # Arrange: создаем оптимизатор с select_related
        from candle_providers.models import CandleProvider
        from candle_sources.models import CandleSource
        from exchange_clients.models import ExchangeClient
        from exchanges.models import Exchange, TradingPair

        exchange = Exchange.objects.create(
            name="Test Exchange", class_name="ByBitExchangeClient"
        )
        trading_pair = TradingPair.objects.create(
            name="BTC/USDT",
            symbol="BTC/USDT:USDT",
            min_amount=Decimal("0.001"),
            max_amount=Decimal("1000"),
            fee_percent=Decimal("0.1"),
        )
        exchange_client = ExchangeClient.objects.create(
            exchange=exchange,
            api_key="test_key",
            api_secret="test_secret",
            name="Test Client",
        )
        candle_source = CandleSource.objects.create(
            exchange_client=exchange_client,
            trading_pair=trading_pair,
            timeframe="1h",
        )
        candle_provider = CandleProvider.objects.create(
            class_name="PlainCandleProvider",
            primary_source=candle_source,
        )
        algorithm = TraderOptimizationAlgorithm.objects.create(
            name="Test Optuna",
            class_name="OptunaOptimizationAlgorithm",
            arguments={"n_trials": 10},
        )
        optimizer = TraderOptimizer.objects.create(
            algorithm=algorithm,
            exchange=exchange,
            candle_provider=candle_provider,
            strategy_class_name="MoneyFlowIndexStrategy",
            risk_manager_class_name="SLPercentTPPercentPSAllInRiskManager",
            initial_balance=Decimal("1000"),
            max_positions_count=1,
        )

        # Act & Assert: проверяем количество запросов
        with CaptureQueriesContext(connection) as queries:
            optimizer_optimize(optimizer_id=optimizer.pk)

        # Ожидаем: 1 запрос для получения оптимизатора
        # (optimize() замокан, поэтому дополнительных запросов нет)
        assert len(queries) == 1


@pytest.mark.django_db
class TestOptimizeOldOptimizers:
    """Тесты для задачи optimize_old_optimizers."""

    def test_optimize_old_optimizers_skips_when_active_optimization(
        self, db, mock_optimizer_optimize
    ):
        """Тест пропускает запуск если есть активная оптимизация."""
        # Arrange: создаем оптимизатор со статусом REBOOTING
        from candle_providers.models import CandleProvider
        from candle_sources.models import CandleSource
        from exchange_clients.models import ExchangeClient
        from exchanges.models import Exchange, TradingPair

        exchange = Exchange.objects.create(
            name="Test Exchange", class_name="ByBitExchangeClient"
        )
        trading_pair = TradingPair.objects.create(
            name="BTC/USDT",
            symbol="BTC/USDT:USDT",
            min_amount=Decimal("0.001"),
            max_amount=Decimal("1000"),
            fee_percent=Decimal("0.1"),
        )
        exchange_client = ExchangeClient.objects.create(
            exchange=exchange,
            api_key="test_key",
            api_secret="test_secret",
            name="Test Client",
        )
        candle_source = CandleSource.objects.create(
            exchange_client=exchange_client,
            trading_pair=trading_pair,
            timeframe="1h",
        )
        candle_provider = CandleProvider.objects.create(
            class_name="PlainCandleProvider",
            primary_source=candle_source,
        )
        algorithm = TraderOptimizationAlgorithm.objects.create(
            name="Test Optuna",
            class_name="OptunaOptimizationAlgorithm",
            arguments={"n_trials": 10},
        )
        TraderOptimizer.objects.create(
            algorithm=algorithm,
            exchange=exchange,
            candle_provider=candle_provider,
            strategy_class_name="MoneyFlowIndexStrategy",
            risk_manager_class_name="SLPercentTPPercentPSAllInRiskManager",
            initial_balance=Decimal("1000"),
            max_positions_count=1,
            status=OptimizerStatus.REBOOTING,
        )

        # Act: вызываем задачу
        with CaptureQueriesContext(connection) as queries:
            optimize_old_optimizers()

        # Assert: должен быть только 1 запрос для проверки статуса
        assert len(queries) == 1
        # optimize() не должен вызываться
        mock_optimizer_optimize.assert_not_called()

    def test_optimize_old_optimizers_selects_oldest_result(
        self, db, mock_optimizer_optimize
    ):
        """Тест выбирает оптимизатор с самым старым результатом."""
        # Arrange: создаем несколько оптимизаторов с результатами
        from candle_providers.models import CandleProvider
        from candle_sources.models import CandleSource
        from exchange_clients.models import ExchangeClient
        from exchanges.models import Exchange, TradingPair
        from optimizers.models import TraderOptimizationResult

        exchange = Exchange.objects.create(
            name="Test Exchange", class_name="ByBitExchangeClient"
        )
        trading_pair = TradingPair.objects.create(
            name="BTC/USDT",
            symbol="BTC/USDT:USDT",
            min_amount=Decimal("0.001"),
            max_amount=Decimal("1000"),
            fee_percent=Decimal("0.1"),
        )
        exchange_client = ExchangeClient.objects.create(
            exchange=exchange,
            api_key="test_key",
            api_secret="test_secret",
            name="Test Client",
        )
        candle_source = CandleSource.objects.create(
            exchange_client=exchange_client,
            trading_pair=trading_pair,
            timeframe="1h",
        )
        candle_provider = CandleProvider.objects.create(
            class_name="PlainCandleProvider",
            primary_source=candle_source,
        )
        algorithm = TraderOptimizationAlgorithm.objects.create(
            name="Test Optuna",
            class_name="OptunaOptimizationAlgorithm",
            arguments={"n_trials": 10},
        )

        # Создаем оптимизатор с новым результатом
        optimizer_new = TraderOptimizer.objects.create(
            algorithm=algorithm,
            exchange=exchange,
            candle_provider=candle_provider,
            strategy_class_name="MoneyFlowIndexStrategy",
            risk_manager_class_name="SLPercentTPPercentPSAllInRiskManager",
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
            created_at=timezone.now(),  # Новый результат
        )

        # Создаем оптимизатор со старым результатом (другие параметры)
        optimizer_old = TraderOptimizer.objects.create(
            algorithm=algorithm,
            exchange=exchange,
            candle_provider=candle_provider,
            strategy_class_name="StochasticStrategy",  # Другая стратегия
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
            created_at=timezone.now()
            - timezone.timedelta(days=10),  # Старый
        )

        # Act: вызываем задачу с мокированием delay
        with patch(
            "optimizers.tasks.optimizer_optimize.delay"
        ) as mock_delay:
            with CaptureQueriesContext(connection) as queries:
                optimize_old_optimizers()

        # Assert: должен выбрать оптимизатор со старым результатом
        # Запросы:
        # 1. Проверка статуса REBOOTING
        # 2. Выбор оптимизатора с самым старым результатом
        assert len(queries) == 2
        mock_delay.assert_called_once_with(optimizer_old.pk)

    def test_optimize_old_optimizers_no_results(
        self, db, mock_optimizer_optimize
    ):
        """Тест когда нет оптимизаторов с результатами."""
        # Arrange: создаем оптимизатор БЕЗ результатов
        from candle_providers.models import CandleProvider
        from candle_sources.models import CandleSource
        from exchange_clients.models import ExchangeClient
        from exchanges.models import Exchange, TradingPair

        exchange = Exchange.objects.create(
            name="Test Exchange", class_name="ByBitExchangeClient"
        )
        trading_pair = TradingPair.objects.create(
            name="BTC/USDT",
            symbol="BTC/USDT:USDT",
            min_amount=Decimal("0.001"),
            max_amount=Decimal("1000"),
            fee_percent=Decimal("0.1"),
        )
        exchange_client = ExchangeClient.objects.create(
            exchange=exchange,
            api_key="test_key",
            api_secret="test_secret",
            name="Test Client",
        )
        candle_source = CandleSource.objects.create(
            exchange_client=exchange_client,
            trading_pair=trading_pair,
            timeframe="1h",
        )
        candle_provider = CandleProvider.objects.create(
            class_name="PlainCandleProvider",
            primary_source=candle_source,
        )
        algorithm = TraderOptimizationAlgorithm.objects.create(
            name="Test Optuna",
            class_name="OptunaOptimizationAlgorithm",
            arguments={"n_trials": 10},
        )
        TraderOptimizer.objects.create(
            algorithm=algorithm,
            exchange=exchange,
            candle_provider=candle_provider,
            strategy_class_name="MoneyFlowIndexStrategy",
            risk_manager_class_name="SLPercentTPPercentPSAllInRiskManager",
            initial_balance=Decimal("1000"),
            max_positions_count=1,
            status=OptimizerStatus.ENABLED,
        )

        # Act: вызываем задачу
        with patch(
            "optimizers.tasks.optimizer_optimize.delay"
        ) as mock_delay:
            with CaptureQueriesContext(connection) as queries:
                optimize_old_optimizers()

        # Assert: не должно быть вызова optimize
        assert len(queries) == 2
        mock_delay.assert_not_called()

    def test_optimize_old_optimizers_query_count(
        self, db, mock_optimizer_optimize
    ):
        """Тест проверяет количество запросов."""
        # Act: вызываем без данных
        with CaptureQueriesContext(connection) as queries:
            optimize_old_optimizers()

        # Assert:
        # 1. Проверка наличия REBOOTING оптимизаторов
        # 2. Поиск оптимизатора с результатами
        assert len(queries) == 2
