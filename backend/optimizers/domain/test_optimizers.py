"""
Тесты для доменной модели оптимизаторов.

Покрывает:
- OptunaOptimizationAlgorithm
- GenerationOptimizationAlgorithm
- TraderOptimizer
- Вычисление метрик (ROI, Sharpe, R², Win Rate)
- Нормализация и весовые коэффициенты
"""

from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from exchanges.domain import Timeframe
from risk_managers.domain import SLPercentTPPercentPSAllInRiskManager
from strategies.domain import MoneyFlowIndexStrategy
from traders.domain import Trader, TraderStatus

from .optimizers import (
    GenerationOptimizationAlgorithm,
    OptunaOptimizationAlgorithm,
    TraderOptimizer,
)
from .shemas import OptimizationResult, TraderOptimizationResult


# ==========================================================================
# Тесты OptunaOptimizationAlgorithm
# ==========================================================================


class TestOptunaOptimizationAlgorithm:
    """Тесты для Bayesian оптимизации через Optuna."""

    def test_initialization(self):
        """Тест инициализации с параметрами по умолчанию."""
        optimizer = OptunaOptimizationAlgorithm()
        assert optimizer.n_trials == 500

    def test_initialization_custom_trials(self):
        """Тест инициализации с пользовательским числом trials."""
        optimizer = OptunaOptimizationAlgorithm(n_trials=100)
        assert optimizer.n_trials == 100

    def test_optimize_integer_params(self, simple_score_function):
        """Тест оптимизации с целочисленными параметрами."""
        optimizer = OptunaOptimizationAlgorithm(n_trials=50)
        params_constraints = {
            "param1": (1, 10),
            "param2": (1, 10),
        }

        result = optimizer.optimize(
            score_function=simple_score_function,
            params_constraints=params_constraints,
        )

        assert isinstance(result, OptimizationResult)
        assert result.value > 0
        assert "param1" in result.params
        assert "param2" in result.params
        assert 1 <= result.params["param1"] <= 10
        assert 1 <= result.params["param2"] <= 10

    def test_optimize_float_params(self, simple_score_function):
        """Тест оптимизации с вещественными параметрами."""
        optimizer = OptunaOptimizationAlgorithm(n_trials=50)
        params_constraints = {
            "x": (0.0, 10.0),
            "y": (0.0, 10.0),
        }

        result = optimizer.optimize(
            score_function=simple_score_function,
            params_constraints=params_constraints,
        )

        assert isinstance(result, OptimizationResult)
        assert result.value > 0
        assert 0.0 <= result.params["x"] <= 10.0
        assert 0.0 <= result.params["y"] <= 10.0

    def test_optimize_mixed_params(self, simple_score_function):
        """Тест оптимизации со смешанными типами параметров."""
        optimizer = OptunaOptimizationAlgorithm(n_trials=30)
        params_constraints = {
            "int_param": (1, 100),
            "float_param": (0.1, 10.0),
        }

        result = optimizer.optimize(
            score_function=simple_score_function,
            params_constraints=params_constraints,
        )

        assert isinstance(result.params["int_param"], int)
        assert isinstance(result.params["float_param"], float)

    def test_optimize_quadratic_function(self, quadratic_score_function):
        """Тест нахождения оптимума квадратичной функции."""
        optimizer = OptunaOptimizationAlgorithm(n_trials=100)
        params_constraints = {
            "x": (0.0, 10.0),
            "y": (0.0, 10.0),
        }

        result = optimizer.optimize(
            score_function=quadratic_score_function,
            params_constraints=params_constraints,
        )

        # Оптимум должен быть близок к (5, 5)
        assert 4.0 <= result.params["x"] <= 6.0
        assert 4.0 <= result.params["y"] <= 6.0
        assert result.value >= 45  # Близко к максимуму 50

    def test_optimize_raises_on_invalid_type(self, simple_score_function):
        """Тест ошибки при неподдерживаемом типе параметра."""
        optimizer = OptunaOptimizationAlgorithm(n_trials=10)
        params_constraints = {
            "invalid_param": ("string", "another_string"),
        }

        with pytest.raises(
            ValueError, match="Неподдерживаемый тип диапазона"
        ):
            optimizer.optimize(
                score_function=simple_score_function,
                params_constraints=params_constraints,
            )


# ==========================================================================
# Тесты GenerationOptimizationAlgorithm
# ==========================================================================


class TestGenerationOptimizationAlgorithm:
    """Тесты для генетического алгоритма через DEAP."""

    def test_initialization(self):
        """Тест инициализации с параметрами по умолчанию."""
        optimizer = GenerationOptimizationAlgorithm()
        assert optimizer.generations == 50
        assert optimizer.population_size == 100

    def test_initialization_custom_params(self):
        """Тест инициализации с пользовательскими параметрами."""
        optimizer = GenerationOptimizationAlgorithm(
            generations=20, population_size=50
        )
        assert optimizer.generations == 20
        assert optimizer.population_size == 50

    def test_optimize_integer_params(self, simple_score_function):
        """Тест оптимизации с целочисленными параметрами."""
        optimizer = GenerationOptimizationAlgorithm(
            generations=10, population_size=20
        )
        params_constraints = {
            "param1": (1, 10),
            "param2": (1, 10),
        }

        result = optimizer.optimize(
            score_function=simple_score_function,
            params_constraints=params_constraints,
        )

        assert isinstance(result, OptimizationResult)
        assert result.value > 0
        assert 1 <= result.params["param1"] <= 10
        assert 1 <= result.params["param2"] <= 10


# ==========================================================================
# Тесты TraderOptimizer
# ==========================================================================


class TestTraderOptimizer:
    """Тесты для основного класса оптимизации трейдера."""

    def test_initialization(self, mock_candle_provider, trading_pair):
        """Тест инициализации TraderOptimizer."""
        optimizer = TraderOptimizer(
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 2, 1),
            optimization_algorithm=OptunaOptimizationAlgorithm(n_trials=10),
            candle_provider=mock_candle_provider,
            trading_pair=trading_pair,
            timeframe=Timeframe.ONE_HOUR,
            strategy_class=MoneyFlowIndexStrategy,
            risk_manager_class=SLPercentTPPercentPSAllInRiskManager,
            initial_balance=Decimal("1000"),
            max_positions_count=1,
        )

        assert optimizer.trading_pair == trading_pair
        assert optimizer.timeframe == Timeframe.ONE_HOUR
        assert optimizer.strategy_class == MoneyFlowIndexStrategy
        risk_mgr_cls = SLPercentTPPercentPSAllInRiskManager
        assert optimizer.risk_manager_class == risk_mgr_cls
        assert optimizer.initial_balance == Decimal("1000")
        assert optimizer.roi_weight == Decimal("0.4")
        assert optimizer.r2_weight == Decimal("0.3")
        assert optimizer.sharpe_weight == Decimal("0.2")
        assert optimizer.win_rate_weight == Decimal("0.1")

    def test_initialization_custom_weights(
        self, mock_candle_provider, trading_pair
    ):
        """Тест инициализации с пользовательскими весами метрик."""
        optimizer = TraderOptimizer(
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 2, 1),
            optimization_algorithm=OptunaOptimizationAlgorithm(n_trials=10),
            candle_provider=mock_candle_provider,
            trading_pair=trading_pair,
            timeframe=Timeframe.ONE_HOUR,
            strategy_class=MoneyFlowIndexStrategy,
            risk_manager_class=SLPercentTPPercentPSAllInRiskManager,
            initial_balance=Decimal("1000"),
            max_positions_count=1,
            roi_weight=Decimal("0.5"),
            r2_weight=Decimal("0.3"),
            sharpe_weight=Decimal("0.1"),
            win_rate_weight=Decimal("0.1"),
        )

        assert optimizer.roi_weight == Decimal("0.5")
        assert optimizer.r2_weight == Decimal("0.3")
        assert optimizer.sharpe_weight == Decimal("0.1")
        assert optimizer.win_rate_weight == Decimal("0.1")

    def test_initialization_raises_on_invalid_weights(
        self, mock_candle_provider, trading_pair
    ):
        """Тест ошибки при сумме весов > 1.0."""
        with pytest.raises(
            ValueError, match="Сумма весов должна быть не больше 1.0"
        ):
            TraderOptimizer(
                start_date=datetime(2024, 1, 1),
                end_date=datetime(2024, 2, 1),
                optimization_algorithm=OptunaOptimizationAlgorithm(
                    n_trials=10
                ),
                candle_provider=mock_candle_provider,
                trading_pair=trading_pair,
                timeframe=Timeframe.ONE_HOUR,
                strategy_class=MoneyFlowIndexStrategy,
                risk_manager_class=SLPercentTPPercentPSAllInRiskManager,
                initial_balance=Decimal("1000"),
                max_positions_count=1,
                roi_weight=Decimal("0.6"),
                r2_weight=Decimal("0.6"),  # Сумма = 1.2 > 1.0
                sharpe_weight=Decimal("0.1"),
                win_rate_weight=Decimal("0.1"),
            )

    def test_get_trader_creates_valid_trader(
        self, mock_candle_provider, trading_pair
    ):
        """Тест создания трейдера с заданными параметрами."""
        optimizer = TraderOptimizer(
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 2, 1),
            optimization_algorithm=OptunaOptimizationAlgorithm(n_trials=10),
            candle_provider=mock_candle_provider,
            trading_pair=trading_pair,
            timeframe=Timeframe.ONE_HOUR,
            strategy_class=MoneyFlowIndexStrategy,
            risk_manager_class=SLPercentTPPercentPSAllInRiskManager,
            initial_balance=Decimal("1000"),
            max_positions_count=2,
            trail_stop_enabled=True,
        )

        params = {
            "strategy_period": 14,
            "strategy_overbought": 80,
            "strategy_oversold": 20,
            "strategy_median": 50,
            "risk_manager_stop_loss_percent": 2.0,
            "risk_manager_take_profit_percent": 4.0,
        }

        trader = optimizer.get_trader(params)

        assert isinstance(trader, Trader)
        assert trader.trading_pair == trading_pair
        assert trader.timeframe == Timeframe.ONE_HOUR
        assert trader.initial_balance == Decimal("1000")
        assert trader.max_positions_count == 2
        assert trader.trail_stop_enabled is True
        assert trader.create_new_orders is False  # Бэктест режим
        assert trader.check_drawdown is False  # Бэктест режим
        assert trader.status == TraderStatus.REBOOTING

        # Проверка параметров стратегии
        assert isinstance(trader.strategy, MoneyFlowIndexStrategy)
        assert trader.strategy.period == 14
        assert trader.strategy.overbought == 80
        assert trader.strategy.oversold == 20
        assert trader.strategy.median == 50

        # Проверка параметров риск-менеджера
        risk_mgr_cls = SLPercentTPPercentPSAllInRiskManager
        assert isinstance(trader.risk_manager, risk_mgr_cls)
        assert trader.risk_manager.stop_loss_percent == Decimal("2.0")
        assert trader.risk_manager.take_profit_percent == Decimal("4.0")

    def test_normalize_sigmoid(self):
        """Тест нормализации через sigmoid функцию."""
        # sigmoid(0) = 0.5
        result = TraderOptimizer.normalize_sigmoid(Decimal("0"))
        assert result == Decimal("0.5")

        # sigmoid(очень большое число) ≈ 1
        result = TraderOptimizer.normalize_sigmoid(Decimal("10"))
        assert result > Decimal("0.99")

        # sigmoid(очень малое число) ≈ 0
        result = TraderOptimizer.normalize_sigmoid(Decimal("-10"))
        assert result < Decimal("0.01")

        # sigmoid всегда в диапазоне (0, 1)
        for value in [Decimal(x) for x in [-5, -1, 0, 1, 5]]:
            result = TraderOptimizer.normalize_sigmoid(value)
            assert Decimal("0") < result < Decimal("1")

    @patch("optimizers.domain.optimizers.asyncio.run")
    def test_get_score_calculates_composite_metric(
        self, mock_asyncio_run, mock_candle_provider, trading_pair
    ):
        """Тест расчета комбинированной метрики score."""
        optimizer = TraderOptimizer(
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 2, 1),
            optimization_algorithm=OptunaOptimizationAlgorithm(n_trials=10),
            candle_provider=mock_candle_provider,
            trading_pair=trading_pair,
            timeframe=Timeframe.ONE_HOUR,
            strategy_class=MoneyFlowIndexStrategy,
            risk_manager_class=SLPercentTPPercentPSAllInRiskManager,
            initial_balance=Decimal("1000"),
            max_positions_count=1,
            roi_weight=Decimal("0.4"),
            r2_weight=Decimal("0.3"),
            sharpe_weight=Decimal("0.2"),
            win_rate_weight=Decimal("0.1"),
        )

        # Mock трейдера с известными метриками
        mock_trader = MagicMock(spec=Trader)
        mock_trader.get_roi.return_value = Decimal("0.5")
        mock_trader.get_pnl_r2.return_value = Decimal("0.8")
        mock_trader.get_sharpe_ratio.return_value = Decimal("1.5")
        mock_trader.get_win_rate.return_value = Decimal("0.6")

        with patch.object(optimizer, "get_trader", return_value=mock_trader):
            params = {
                "strategy_period": 14,
                "strategy_overbought": 80,
                "strategy_oversold": 20,
                "strategy_median": 50,
                "risk_manager_stop_loss_percent": 2.0,
                "risk_manager_take_profit_percent": 4.0,
            }

            score = optimizer.get_score(params)

        # Score должен быть взвешенной суммой нормализованных метрик
        assert isinstance(score, Decimal)
        assert score > Decimal("0")
        assert score <= Decimal("1")  # Максимальный score = 1.0


# ==========================================================================
# Тесты схем (Pydantic models)
# ==========================================================================


class TestOptimizationSchemas:
    """Тесты для Pydantic схем оптимизации."""

    def test_optimization_result_schema(self):
        """Тест создания OptimizationResult."""
        result = OptimizationResult(
            value=0.85,
            params={
                "strategy_period": 14,
                "risk_manager_stop_loss_percent": 2.0,
            },
        )

        assert result.value == 0.85
        assert result.params["strategy_period"] == 14
        assert result.params["risk_manager_stop_loss_percent"] == 2.0

    def test_trader_optimization_result_schema(self):
        """Тест создания TraderOptimizationResult."""
        result = TraderOptimizationResult(
            pnl=Decimal("150.50"),
            win_rate=Decimal("0.65"),
            avg_candles_per_position=Decimal("12.5"),
            pnl_r2=Decimal("0.82"),
            roi=Decimal("0.15"),
            sharpe=Decimal("1.8"),
            total_positions=25,
            strategy_arguments={"period": 14, "overbought": 80},
            risk_manager_arguments={"stop_loss_percent": 2.0},
            duration=timedelta(minutes=30),
        )

        assert result.pnl == Decimal("150.50")
        assert result.win_rate == Decimal("0.65")
        assert result.roi == Decimal("0.15")
        assert result.sharpe == Decimal("1.8")
        assert result.total_positions == 25
        assert result.duration == timedelta(minutes=30)
