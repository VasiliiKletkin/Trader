"""
Тесты доменных оптимизаций arbitrage_traders.
Фокус: normalize_sigmoid, get_trader, get_score, алгоритмы оптимизации.
"""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from arbitrage_traders.domain.optimizations import (
    GenerationOptimizationAlgorithm,
    OptunaOptimizationAlgorithm,
)
from arbitrage_traders.domain.optimizations.optimizations import (
    ArbitrageTraderOptimizer,
)
from arbitrage_traders.domain.risk_managers import (
    PSAllInArbitrageRiskManager,
    PSPercentArbitrageRiskManager,
)
from arbitrage_traders.domain.schemas import OptimizationResult, TraderStatus
from arbitrage_traders.domain.strategies import SpreadReversionArbitrageStrategy
from exchanges.domain import MarketType, Timeframe, TradingPair

# ==================== Helpers ====================


def _make_optimizer(**kwargs) -> ArbitrageTraderOptimizer:
    """Создаёт ArbitrageTraderOptimizer с моками."""
    defaults = {
        "optimization_algorithm": MagicMock(),
        "get_candle_iterator": lambda: iter([]),
        "left_trading_pair": TradingPair(
            name="BTC/USDT",
            symbol="BTC/USDT:USDT",
            base_currency="BTC",
            quote_currency="USDT",
            market_type=MarketType.FUTURES,
            taker_fee=Decimal("0.001"),
            maker_fee=Decimal("0.001"),
        ),
        "right_trading_pair": TradingPair(
            name="BTC/USDT",
            symbol="BTC/USDT:USDT",
            base_currency="BTC",
            quote_currency="USDT",
            market_type=MarketType.FUTURES,
            taker_fee=Decimal("0.001"),
            maker_fee=Decimal("0.001"),
        ),
        "timeframe": Timeframe.ONE_HOUR,
        "strategy_class": SpreadReversionArbitrageStrategy,
        "risk_manager_class": PSAllInArbitrageRiskManager,
        "initial_balance": Decimal("1000"),
        "max_positions_count": 1,
    }
    defaults.update(kwargs)
    return ArbitrageTraderOptimizer(**defaults)


# ==================== normalize_sigmoid ====================


class TestNormalizeSigmoid:
    """Тесты статического метода normalize_sigmoid."""

    def test_zero_returns_half(self):
        """sigmoid(0) = 0.5."""
        result = ArbitrageTraderOptimizer.normalize_sigmoid(Decimal("0"))
        assert float(result) == pytest.approx(0.5)

    def test_large_positive_close_to_one(self):
        """Большое положительное → ~1.0."""
        result = ArbitrageTraderOptimizer.normalize_sigmoid(Decimal("10"))
        assert float(result) > 0.99

    def test_large_negative_close_to_zero(self):
        """Большое отрицательное → ~0.0."""
        result = ArbitrageTraderOptimizer.normalize_sigmoid(Decimal("-10"))
        assert float(result) < 0.01


# ==================== __init__ ====================


class TestArbitrageTraderOptimizerInit:
    """Тесты инициализации ArbitrageTraderOptimizer."""

    def test_correct_initialization(self):
        """Все поля корректно инициализируются."""
        opt = _make_optimizer()
        assert opt.initial_balance == Decimal("1000")
        assert opt.strategy_class is SpreadReversionArbitrageStrategy
        assert opt.risk_manager_class is PSAllInArbitrageRiskManager

    def test_weight_sum_exceeds_one_raises(self):
        """Сумма весов > 1.0 → ValueError."""
        with pytest.raises(ValueError):
            _make_optimizer(
                roi_weight=Decimal("0.5"),
                r2_weight=Decimal("0.3"),
                sharpe_weight=Decimal("0.2"),
                win_rate_weight=Decimal("0.2"),  # итого 1.2
            )


# ==================== get_trader ====================


class TestArbitrageTraderOptimizerGetTrader:
    """Тесты get_trader: создание трейдера из параметров."""

    def test_strategy_params_without_prefix(self):
        """Убирает prefix 'strategy_' из параметров."""
        opt = _make_optimizer()
        trader = opt.get_trader(
            {
                "strategy_open_threshold": 0.02,
                "strategy_close_threshold": 0.005,
            }
        )
        assert trader.strategy.open_threshold == 0.02
        assert trader.strategy.close_threshold == 0.005

    def test_risk_manager_params_without_prefix(self):
        """Убирает prefix 'risk_manager_'."""
        opt = _make_optimizer(risk_manager_class=PSPercentArbitrageRiskManager)
        trader = opt.get_trader(
            {
                "strategy_open_threshold": 0.01,
                "strategy_close_threshold": 0.002,
                "risk_manager_position_size_percent": 75.0,
            }
        )
        assert trader.risk_manager.position_size_percent == Decimal("75.0")

    def test_trader_status_rebooting(self):
        """Трейдер создаётся в статусе REBOOTING."""
        opt = _make_optimizer()
        trader = opt.get_trader(
            {
                "strategy_open_threshold": 0.01,
                "strategy_close_threshold": 0.002,
            }
        )
        assert trader.status == TraderStatus.REBOOTING
        assert trader.create_new_orders is False


# ==================== get_score ====================


class TestArbitrageTraderOptimizerGetScore:
    """Тесты get_score: оценка параметров."""

    def test_calls_reboot_and_returns_score(self):
        """Вызывает reboot и возвращает score."""
        opt = _make_optimizer()

        params = {"strategy_open_threshold": 0.01, "strategy_close_threshold": 0.002}
        score = opt.get_score(params)
        assert isinstance(score, Decimal)

    def test_score_is_weighted_sum(self):
        """Score = weighted sum of normalized metrics."""
        opt = _make_optimizer(
            roi_weight=Decimal("1.0"),
            r2_weight=Decimal("0.0"),
            sharpe_weight=Decimal("0.0"),
            win_rate_weight=Decimal("0.0"),
        )

        params = {"strategy_open_threshold": 0.01, "strategy_close_threshold": 0.002}
        score = opt.get_score(params)
        # С roi_weight=1.0 и roi=0 (нет позиций), sigmoid(0)=0.5
        assert float(score) == pytest.approx(0.5, abs=0.01)


# ==================== OptunaOptimizationAlgorithm ====================


class TestOptunaOptimizationAlgorithm:
    """Тесты OptunaOptimizationAlgorithm."""

    def test_optimize_calls_score_function(self):
        """optimize вызывает score_function."""
        algo = OptunaOptimizationAlgorithm(n_trials=3)
        call_count = 0

        def score_fn(params):
            nonlocal call_count
            call_count += 1
            return Decimal("1.0")

        algo.optimize(
            score_function=score_fn,
            params_constraints={"x": (0.0, 10.0)},
        )
        assert call_count == 3

    def test_returns_optimization_result(self):
        """Возвращает OptimizationResult."""
        algo = OptunaOptimizationAlgorithm(n_trials=2)
        result = algo.optimize(
            score_function=lambda params: Decimal(str(params["x"])),
            params_constraints={"x": (0.0, 10.0)},
        )
        assert isinstance(result, OptimizationResult)
        assert "x" in result.params

    def test_n_trials_controls_calls(self):
        """n_trials управляет количеством вызовов."""
        call_count = 0

        def score_fn(params):
            nonlocal call_count
            call_count += 1
            return Decimal("0.5")

        algo = OptunaOptimizationAlgorithm(n_trials=5)
        algo.optimize(score_function=score_fn, params_constraints={"x": (0.0, 1.0)})
        assert call_count == 5


# ==================== GenerationOptimizationAlgorithm ====================


class TestGenerationOptimizationAlgorithm:
    """Тесты GenerationOptimizationAlgorithm."""

    def test_optimize_calls_score_function(self):
        """optimize вызывает score_function."""
        algo = GenerationOptimizationAlgorithm(generations=2, population_size=5)
        called = False

        def score_fn(params):
            nonlocal called
            called = True
            return Decimal("1.0")

        algo.optimize(
            score_function=score_fn,
            # cxTwoPoint: min 2 параметра; int чтобы mutUniformInt
            params_constraints={"x": (0, 10), "y": (0, 5)},
        )
        assert called is True

    def test_returns_optimization_result(self):
        """Возвращает OptimizationResult."""
        algo = GenerationOptimizationAlgorithm(generations=2, population_size=5)
        result = algo.optimize(
            score_function=lambda params: Decimal(str(abs(params.get("x", 0)))),
            params_constraints={"x": (0, 10), "y": (0, 5)},
        )
        assert isinstance(result, OptimizationResult)
        assert "x" in result.params
