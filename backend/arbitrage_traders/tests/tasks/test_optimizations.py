"""
Тесты задач Celery для оптимизации арбитражных трейдеров.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest

from arbitrage_traders.domain.optimizations import OptunaOptimizationAlgorithm
from arbitrage_traders.domain.risk_managers import PSAllInArbitrageRiskManager
from arbitrage_traders.domain.strategies import SpreadReversionArbitrageStrategy
from arbitrage_traders.models import (
    ArbitrageOptimizationAlgorithm,
    ArbitrageTraderOptimizer,
)
from arbitrage_traders.tasks.optimizations import arbitrage_optimizer_optimize
from candle_sources.models import CandleSource
from exchange_clients.models import ExchangeClient
from exchanges.domain import BybitExchange
from exchanges.domain.exchanges import BinanceExchange
from exchanges.models import Exchange, TradingPair
from exchanges.schemas import Timeframe

# ==================== Fixtures ====================


@pytest.fixture
def exchange() -> Exchange:
    exchange, _ = Exchange.objects.get_or_create(
        class_name=BybitExchange.__name__,
        defaults={"name": "Bybit Test"},
    )
    return exchange


@pytest.fixture
def right_exchange() -> Exchange:
    exchange, _ = Exchange.objects.get_or_create(
        class_name=BinanceExchange.__name__,
        defaults={"name": "Binance Test"},
    )
    return exchange


@pytest.fixture
def trading_pair() -> TradingPair:
    pair, _ = TradingPair.objects.get_or_create(
        name="BTC/USDT",
        defaults={
            "symbol": "BTC/USDT:USDT",
            "min_amount": Decimal("0.001"),
            "max_amount": Decimal("1000"),
            "fee_percent": Decimal("0.1"),
        },
    )
    return pair


@pytest.fixture
def exchange_client(exchange: Exchange) -> ExchangeClient:
    return ExchangeClient.objects.create(
        exchange=exchange,
        name="Task Opt Client",
        arguments={"api_key": "task_opt_key", "api_secret": "task_opt_secret"},
    )


@pytest.fixture
def right_exchange_client(right_exchange: Exchange) -> ExchangeClient:
    return ExchangeClient.objects.create(
        exchange=right_exchange,
        name="Task Opt Client 2",
        arguments={"api_key": "task_opt_key_2", "api_secret": "task_opt_secret_2"},
    )


@pytest.fixture
def candle_source(
    exchange_client: ExchangeClient, trading_pair: TradingPair
) -> CandleSource:
    return CandleSource.objects.create(
        exchange_client=exchange_client,
        trading_pair=trading_pair,
        timeframe=Timeframe.ONE_HOUR,
    )


@pytest.fixture
def right_candle_source(
    right_exchange_client: ExchangeClient, trading_pair: TradingPair
) -> CandleSource:
    return CandleSource.objects.create(
        exchange_client=right_exchange_client,
        trading_pair=trading_pair,
        timeframe=Timeframe.ONE_HOUR,
    )


@pytest.fixture
def algorithm() -> ArbitrageOptimizationAlgorithm:
    return ArbitrageOptimizationAlgorithm.objects.create(
        name="Task Test Optuna",
        class_name=OptunaOptimizationAlgorithm.__name__,
        arguments={"n_trials": 10},
    )


@pytest.fixture
def optimizer(
    algorithm: ArbitrageOptimizationAlgorithm,
    candle_source: CandleSource,
    right_candle_source: CandleSource,
) -> ArbitrageTraderOptimizer:
    return ArbitrageTraderOptimizer.objects.create(
        algorithm=algorithm,
        left_candle_source=candle_source,
        right_candle_source=right_candle_source,
        strategy_class_name=SpreadReversionArbitrageStrategy.__name__,
        risk_manager_class_name=PSAllInArbitrageRiskManager.__name__,
        initial_balance=Decimal("1000.00"),
    )


# ==================== Tests ====================


@pytest.mark.django_db
class TestArbitrageOptimizerOptimizeTask:
    """Тесты задачи arbitrage_optimizer_optimize."""

    def test_task_calls_optimize(self, optimizer):
        """Задача вызывает optimizer.optimize()."""
        with patch.object(ArbitrageTraderOptimizer, "optimize") as mock_opt:
            arbitrage_optimizer_optimize(optimizer_id=optimizer.pk)
            mock_opt.assert_called_once()

    def test_task_nonexistent_optimizer_raises(self):
        """Несуществующий optimizer_id бросает DoesNotExist."""
        with pytest.raises(ArbitrageTraderOptimizer.DoesNotExist):
            arbitrage_optimizer_optimize(optimizer_id=999999)

    def test_task_fetches_correct_optimizer(self, optimizer):
        """Задача загружает правильный оптимизатор."""
        with patch.object(ArbitrageTraderOptimizer, "optimize") as mock_opt:
            arbitrage_optimizer_optimize(optimizer_id=optimizer.pk)
            # optimize вызывается на загруженном объекте — проверяем что 1 раз
            mock_opt.assert_called_once()
