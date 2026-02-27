"""
Тесты моделей оптимизации арбитражных трейдеров.
ArbitrageOptimizationAlgorithm, ArbitrageTraderOptimizer,
ArbitrageTraderOptimizationResult, ArbitrageTraderOptimizerError.
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.db import IntegrityError

from arbitrage_traders.domain import (
    ArbitrageTraderOptimizer as DomainOptimizer,
)
from arbitrage_traders.domain.optimizations import (
    ArbitrageOptimizerRegistry,
    GenerationOptimizationAlgorithm,
    OptunaOptimizationAlgorithm,
)
from arbitrage_traders.domain.optimizations.base import AbstractOptimizationAlgorithm
from arbitrage_traders.domain.risk_managers import (
    PSAllInArbitrageRiskManager,
)
from arbitrage_traders.domain.schemas import (
    ArbitrageTraderOptimizationResult as DomainOptResult,
)
from arbitrage_traders.domain.strategies import (
    SpreadReversionArbitrageStrategy,
)
from arbitrage_traders.models import (
    ArbitrageOptimizationAlgorithm as AlgorithmModel,
)
from arbitrage_traders.models import (
    ArbitrageTraderOptimizationResult,
    ArbitrageTraderOptimizer,
    ArbitrageTraderOptimizerError,
)
from arbitrage_traders.schemas import ArbitrageOptimizerStatus
from candle_sources.models import CandleSource
from exchange_clients.domain import ByBitExchangeClient
from exchange_clients.domain.exchange_clients import BinanceExchangeClient
from exchange_clients.models import ExchangeClient
from exchanges.models import Exchange, TradingPair
from exchanges.schemas import Timeframe

# ==================== Fixtures ====================


@pytest.fixture
def exchange() -> Exchange:
    """Создает тестовую биржу."""
    exchange, _ = Exchange.objects.get_or_create(
        class_name=ByBitExchangeClient.__name__,
        defaults={"name": "Bybit Test"},
    )
    return exchange


@pytest.fixture
def right_exchange() -> Exchange:
    """Создает вторую тестовую биржу."""
    exchange, _ = Exchange.objects.get_or_create(
        class_name=BinanceExchangeClient.__name__,
        defaults={"name": "Binance Test"},
    )
    return exchange


@pytest.fixture
def trading_pair() -> TradingPair:
    """Создает торговую пару."""
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
    """Создает клиента биржи."""
    return ExchangeClient.objects.create(
        exchange=exchange,
        api_key="opt_test_key",
        api_secret="opt_test_secret",
        name="Opt Test Client",
        demo=True,
    )


@pytest.fixture
def right_exchange_client(right_exchange: Exchange) -> ExchangeClient:
    """Создает второго клиента биржи."""
    return ExchangeClient.objects.create(
        exchange=right_exchange,
        api_key="opt_test_key_2",
        api_secret="opt_test_secret_2",
        name="Opt Test Client 2",
        demo=True,
    )


@pytest.fixture
def candle_source(
    exchange_client: ExchangeClient, trading_pair: TradingPair
) -> CandleSource:
    """Создает источник свечей."""
    return CandleSource.objects.create(
        exchange_client=exchange_client,
        trading_pair=trading_pair,
        timeframe=Timeframe.ONE_HOUR,
    )


@pytest.fixture
def right_candle_source(
    right_exchange_client: ExchangeClient, trading_pair: TradingPair
) -> CandleSource:
    """Создает второй источник свечей."""
    return CandleSource.objects.create(
        exchange_client=right_exchange_client,
        trading_pair=trading_pair,
        timeframe=Timeframe.ONE_HOUR,
    )


@pytest.fixture
def algorithm() -> AlgorithmModel:
    """Создает алгоритм оптимизации Optuna."""
    return AlgorithmModel.objects.create(
        name="Test Optuna",
        class_name=OptunaOptimizationAlgorithm.__name__,
        arguments={"n_trials": 10},
    )


@pytest.fixture
def algorithm_generation() -> AlgorithmModel:
    """Создает алгоритм оптимизации Generation."""
    return AlgorithmModel.objects.create(
        name="Test Generation",
        class_name=GenerationOptimizationAlgorithm.__name__,
        arguments={"generations": 5, "population_size": 10},
    )


@pytest.fixture
def optimizer(
    algorithm: AlgorithmModel,
    candle_source: CandleSource,
    right_candle_source: CandleSource,
) -> ArbitrageTraderOptimizer:
    """Создает оптимизатор."""
    return ArbitrageTraderOptimizer.objects.create(
        algorithm=algorithm,
        left_candle_source=candle_source,
        right_candle_source=right_candle_source,
        strategy_class_name=SpreadReversionArbitrageStrategy.__name__,
        risk_manager_class_name=PSAllInArbitrageRiskManager.__name__,
        initial_balance=Decimal("1000.00"),
    )


@pytest.fixture
def optimization_result(
    optimizer: ArbitrageTraderOptimizer,
) -> ArbitrageTraderOptimizationResult:
    """Создает результат оптимизации."""
    return ArbitrageTraderOptimizationResult.objects.create(
        optimizer=optimizer,
        duration=timedelta(minutes=5, seconds=30),
        pnl=Decimal("150.123456789012345678"),
        win_rate=Decimal("0.6500"),
        avg_candles_per_position=Decimal("12.50"),
        pnl_r2=Decimal("0.8500"),
        roi=Decimal("15.0123"),
        sharpe=Decimal("1.2500"),
        total_positions=20,
        strategy_arguments={"open_threshold": 2.0, "close_threshold": 0.5},
        risk_manager_arguments={},
    )


@pytest.fixture
def optimizer_error(
    optimizer: ArbitrageTraderOptimizer,
) -> ArbitrageTraderOptimizerError:
    """Создает ошибку оптимизатора."""
    return ArbitrageTraderOptimizerError.objects.create(
        optimizer=optimizer,
        message="Test optimization error occurred during trial 42",
        traceback="Traceback (most recent call last):\n  File ...",
        type="ValueError",
    )


# ==================== ArbitrageOptimizationAlgorithm ====================


@pytest.mark.django_db
class TestArbitrageOptimizationAlgorithmStr:
    """Тесты __str__ метода."""

    def test_str_format(self, algorithm):
        """__str__ имеет формат 'name (class_name)'."""
        result = str(algorithm)
        assert result == f"Test Optuna ({OptunaOptimizationAlgorithm.__name__})"

    def test_str_generation(self, algorithm_generation):
        """__str__ для Generation алгоритма."""
        result = str(algorithm_generation)
        assert GenerationOptimizationAlgorithm.__name__ in result


@pytest.mark.django_db
class TestArbitrageOptimizationAlgorithmSave:
    """Тесты save() и auto-population аргументов."""

    def test_save_with_explicit_arguments(self, algorithm):
        """При явных аргументах save() не перезаписывает их."""
        assert algorithm.arguments == {"n_trials": 10}

    def test_save_auto_populates_optuna(self):
        """При пустых аргументах Optuna save() заполняет дефолтами."""
        algo = AlgorithmModel.objects.create(
            name="Auto Optuna",
            class_name=OptunaOptimizationAlgorithm.__name__,
        )
        assert "n_trials" in algo.arguments
        assert algo.arguments["n_trials"] == 500

    def test_save_auto_populates_generation(self):
        """При пустых аргументах Generation save() заполняет дефолтами."""
        algo = AlgorithmModel.objects.create(
            name="Auto Generation",
            class_name=GenerationOptimizationAlgorithm.__name__,
        )
        assert "generations" in algo.arguments
        assert "population_size" in algo.arguments
        assert algo.arguments["generations"] == 50
        assert algo.arguments["population_size"] == 100

    def test_save_does_not_overwrite_custom(self):
        """Повторный save() не перезаписывает кастомные аргументы."""
        algo = AlgorithmModel.objects.create(
            name="Custom Optuna",
            class_name=OptunaOptimizationAlgorithm.__name__,
            arguments={"n_trials": 42},
        )
        algo.save()
        algo.refresh_from_db()
        assert algo.arguments["n_trials"] == 42

    def test_unique_name_constraint(self, algorithm):
        """Имя алгоритма уникально."""
        with pytest.raises(IntegrityError):
            AlgorithmModel.objects.create(
                name="Test Optuna",
                class_name=OptunaOptimizationAlgorithm.__name__,
            )


@pytest.mark.django_db
class TestArbitrageOptimizationAlgorithmGetClass:
    """Тесты get_class()."""

    def test_get_class_optuna(self, algorithm):
        """get_class() для Optuna."""
        cls = algorithm.get_class()
        assert cls is OptunaOptimizationAlgorithm

    def test_get_class_generation(self, algorithm_generation):
        """get_class() для Generation."""
        cls = algorithm_generation.get_class()
        assert cls is GenerationOptimizationAlgorithm

    def test_get_class_is_subclass(self, algorithm):
        """Возвращённый класс наследует AbstractOptimizationAlgorithm."""
        cls = algorithm.get_class()
        assert issubclass(cls, AbstractOptimizationAlgorithm)

    def test_get_class_invalid_raises(self):
        """Невалидный class_name бросает ValueError."""
        algo = AlgorithmModel(name="Bad", class_name="NonExistent")
        with pytest.raises(ValueError):
            algo.get_class()


@pytest.mark.django_db
class TestArbitrageOptimizationAlgorithmGetDescription:
    """Тесты get_description()."""

    def test_get_description_returns_string(self, algorithm):
        """get_description() возвращает строку."""
        desc = algorithm.get_description()
        assert isinstance(desc, str)

    def test_get_description_matches_docstring(self, algorithm):
        """get_description() совпадает с docstring класса."""
        cls = algorithm.get_class()
        expected = (cls.__doc__ or "").strip()
        assert algorithm.get_description() == expected


@pytest.mark.django_db
class TestArbitrageOptimizationAlgorithmInstantiate:
    """Тесты instantiate()."""

    def test_instantiate_optuna(self, algorithm):
        """instantiate() создаёт OptunaOptimizationAlgorithm."""
        domain_obj = algorithm.instantiate()
        assert isinstance(domain_obj, OptunaOptimizationAlgorithm)
        assert domain_obj.n_trials == 10

    def test_instantiate_generation(self, algorithm_generation):
        """instantiate() создаёт GenerationOptimizationAlgorithm."""
        domain_obj = algorithm_generation.instantiate()
        assert isinstance(domain_obj, GenerationOptimizationAlgorithm)
        assert domain_obj.generations == 5
        assert domain_obj.population_size == 10

    def test_instantiate_with_duplicate_kwargs_raises(self, algorithm):
        """instantiate() с дублирующим kwarg бросает TypeError."""
        with pytest.raises(TypeError):
            algorithm.instantiate(n_trials=99)


@pytest.mark.django_db
class TestArbitrageOptimizationAlgorithmRegistry:
    """Тесты реестра алгоритмов."""

    def test_registry_contains_optuna(self):
        """Реестр содержит OptunaOptimizationAlgorithm."""
        cls = ArbitrageOptimizerRegistry.get_class(OptunaOptimizationAlgorithm.__name__)
        assert cls is OptunaOptimizationAlgorithm

    def test_registry_contains_generation(self):
        """Реестр содержит GenerationOptimizationAlgorithm."""
        cls = ArbitrageOptimizerRegistry.get_class(
            GenerationOptimizationAlgorithm.__name__
        )
        assert cls is GenerationOptimizationAlgorithm

    def test_registry_choices_not_empty(self):
        """get_choices() не пуст."""
        choices = ArbitrageOptimizerRegistry.get_choices()
        assert len(choices) >= 2


# ==================== ArbitrageTraderOptimizer ====================


@pytest.mark.django_db
class TestArbitrageTraderOptimizerStr:
    """Тесты __str__ метода."""

    def test_str_contains_pk(self, optimizer):
        """__str__ содержит pk оптимизатора."""
        result = str(optimizer)
        assert str(optimizer.pk) in result

    def test_str_contains_trading_pair(self, optimizer, trading_pair):
        """__str__ содержит торговую пару."""
        result = str(optimizer)
        assert trading_pair.name in result


@pytest.mark.django_db
class TestArbitrageTraderOptimizerProperties:
    """Тесты cached_property: timeframe, trading_pair."""

    def test_timeframe_returns_correct_value(self, optimizer):
        """timeframe возвращает Timeframe из left_candle_source."""
        assert optimizer.timeframe == Timeframe.ONE_HOUR

    def test_trading_pair_returns_correct_value(self, optimizer, trading_pair):
        """trading_pair возвращает TradingPair из left_candle_source."""
        assert optimizer.trading_pair == trading_pair

    def test_timeframe_is_cached(self, optimizer):
        """timeframe кэшируется (один и тот же объект)."""
        tf1 = optimizer.timeframe
        tf2 = optimizer.timeframe
        assert tf1 is tf2

    def test_trading_pair_is_cached(self, optimizer):
        """trading_pair кэшируется."""
        tp1 = optimizer.trading_pair
        tp2 = optimizer.trading_pair
        assert tp1 is tp2


@pytest.mark.django_db
class TestArbitrageTraderOptimizerDefaults:
    """Тесты дефолтных значений полей."""

    def test_default_status_enabled(self, optimizer):
        """Дефолтный статус — ENABLED."""
        assert optimizer.status == ArbitrageOptimizerStatus.ENABLED

    def test_default_weights(self, optimizer):
        """Дефолтные веса метрик."""
        assert optimizer.roi_weight == Decimal("0.40")
        assert optimizer.r2_weight == Decimal("0.30")
        assert optimizer.sharpe_weight == Decimal("0.20")
        assert optimizer.win_rate_weight == Decimal("0.10")

    def test_default_max_positions(self, optimizer):
        """Дефолтное max_positions_count = 1."""
        assert optimizer.max_positions_count == 1

    def test_default_close_flags(self, optimizer):
        """Дефолтные флаги закрытия позиций."""
        assert optimizer.close_position_by_opposite_signal is True
        assert optimizer.close_position_by_strategy is True


@pytest.mark.django_db
class TestArbitrageTraderOptimizerInstantiate:
    """Тесты instantiate()."""

    def test_instantiate_returns_domain_object(self, optimizer):
        """instantiate() создаёт DomainArbitrageTraderOptimizer."""
        domain_obj = optimizer.instantiate()
        assert isinstance(domain_obj, DomainOptimizer)

    def test_instantiate_passes_weights(self, optimizer):
        """instantiate() передаёт веса метрик."""
        domain_obj = optimizer.instantiate()
        assert domain_obj.roi_weight == Decimal("0.40")
        assert domain_obj.r2_weight == Decimal("0.30")
        assert domain_obj.sharpe_weight == Decimal("0.20")
        assert domain_obj.win_rate_weight == Decimal("0.10")

    def test_instantiate_passes_balance(self, optimizer):
        """instantiate() передаёт initial_balance."""
        domain_obj = optimizer.instantiate()
        assert domain_obj.initial_balance == Decimal("1000.00")

    def test_instantiate_resolves_strategy_class(self, optimizer):
        """instantiate() резолвит класс стратегии через реестр."""
        domain_obj = optimizer.instantiate()
        assert domain_obj.strategy_class is SpreadReversionArbitrageStrategy

    def test_instantiate_resolves_risk_manager_class(self, optimizer):
        """instantiate() резолвит класс риск-менеджера через реестр."""
        domain_obj = optimizer.instantiate()
        assert domain_obj.risk_manager_class is PSAllInArbitrageRiskManager


@pytest.mark.django_db
class TestArbitrageTraderOptimizerOptimize:
    """Тесты метода optimize()."""

    def test_optimize_sets_rebooting_then_enabled(self, optimizer):
        """optimize() ставит REBOOTING и в конце возвращает ENABLED."""
        mock_result = DomainOptResult(
            pnl=Decimal("100"),
            win_rate=Decimal("0.5"),
            avg_candles_per_position=Decimal("10"),
            pnl_r2=Decimal("0.8"),
            roi=Decimal("10"),
            sharpe=Decimal("1.0"),
            total_positions=5,
            strategy_arguments={"open_threshold": 1.0},
            risk_manager_arguments={},
            duration=timedelta(seconds=10),
        )
        with patch.object(ArbitrageTraderOptimizer, "instantiate") as mock_inst:
            mock_optimizer = MagicMock()
            mock_optimizer.optimize.return_value = mock_result
            mock_inst.return_value = mock_optimizer

            optimizer.optimize()

        optimizer.refresh_from_db()
        assert optimizer.status == ArbitrageOptimizerStatus.ENABLED

    def test_optimize_creates_result(self, optimizer):
        """optimize() создаёт ArbitrageTraderOptimizationResult."""
        mock_result = DomainOptResult(
            pnl=Decimal("200"),
            win_rate=Decimal("0.7"),
            avg_candles_per_position=Decimal("8"),
            pnl_r2=Decimal("0.9"),
            roi=Decimal("20"),
            sharpe=Decimal("1.5"),
            total_positions=10,
            strategy_arguments={"open_threshold": 2.0},
            risk_manager_arguments={},
            duration=timedelta(minutes=1),
        )
        with patch.object(ArbitrageTraderOptimizer, "instantiate") as mock_inst:
            mock_optimizer = MagicMock()
            mock_optimizer.optimize.return_value = mock_result
            mock_inst.return_value = mock_optimizer

            optimizer.optimize()

        results = ArbitrageTraderOptimizationResult.objects.filter(optimizer=optimizer)
        assert results.count() == 1
        result = results.first()
        assert result.pnl == Decimal("200")
        assert result.total_positions == 10

    def test_optimize_skips_if_rebooting(self, optimizer):
        """optimize() пропускает если статус уже REBOOTING."""
        optimizer.status = ArbitrageOptimizerStatus.REBOOTING
        optimizer.save()

        with patch.object(ArbitrageTraderOptimizer, "instantiate") as mock_inst:
            optimizer.optimize()
            mock_inst.assert_not_called()

    def test_optimize_resets_status_on_exception(self, optimizer):
        """optimize() возвращает ENABLED даже при исключении."""
        with patch.object(ArbitrageTraderOptimizer, "instantiate") as mock_inst:
            mock_inst.side_effect = RuntimeError("Optimization failed")

            with pytest.raises(RuntimeError):
                optimizer.optimize()

        optimizer.refresh_from_db()
        assert optimizer.status == ArbitrageOptimizerStatus.ENABLED

    def test_optimize_result_has_correct_strategy_args(self, optimizer):
        """Результат оптимизации содержит аргументы стратегии."""
        mock_result = DomainOptResult(
            pnl=Decimal("50"),
            win_rate=Decimal("0.4"),
            avg_candles_per_position=Decimal("6"),
            pnl_r2=Decimal("0.7"),
            roi=Decimal("5"),
            sharpe=Decimal("0.8"),
            total_positions=3,
            strategy_arguments={"open_threshold": 3.5, "close_threshold": 0.8},
            risk_manager_arguments={"position_size_percent": 75.0},
            duration=timedelta(seconds=30),
        )
        with patch.object(ArbitrageTraderOptimizer, "instantiate") as mock_inst:
            mock_optimizer = MagicMock()
            mock_optimizer.optimize.return_value = mock_result
            mock_inst.return_value = mock_optimizer

            optimizer.optimize()

        result = ArbitrageTraderOptimizationResult.objects.get(optimizer=optimizer)
        assert result.strategy_arguments == {
            "open_threshold": 3.5,
            "close_threshold": 0.8,
        }
        assert result.risk_manager_arguments == {"position_size_percent": 75.0}


@pytest.mark.django_db
class TestArbitrageTraderOptimizerUniqueConstraint:
    """Тесты UniqueConstraint."""

    def test_duplicate_optimizer_raises(
        self, optimizer, algorithm, candle_source, right_candle_source
    ):
        """Дубликат оптимизатора нарушает UniqueConstraint."""
        with pytest.raises(IntegrityError):
            ArbitrageTraderOptimizer.objects.create(
                algorithm=algorithm,
                left_candle_source=candle_source,
                right_candle_source=right_candle_source,
                strategy_class_name=SpreadReversionArbitrageStrategy.__name__,
                risk_manager_class_name=PSAllInArbitrageRiskManager.__name__,
                initial_balance=Decimal("1000.00"),
            )

    def test_different_balance_allowed(
        self, optimizer, algorithm, candle_source, right_candle_source
    ):
        """Разный initial_balance — допустим (разная конфигурация)."""
        opt2 = ArbitrageTraderOptimizer.objects.create(
            algorithm=algorithm,
            left_candle_source=candle_source,
            right_candle_source=right_candle_source,
            strategy_class_name=SpreadReversionArbitrageStrategy.__name__,
            risk_manager_class_name=PSAllInArbitrageRiskManager.__name__,
            initial_balance=Decimal("2000.00"),
        )
        assert opt2.pk is not None


# ==================== ArbitrageTraderOptimizationResult ====================


@pytest.mark.django_db
class TestArbitrageTraderOptimizationResultStr:
    """Тесты __str__ метода."""

    def test_str_contains_optimizer_id(self, optimization_result, optimizer):
        """__str__ содержит optimizer_id."""
        result = str(optimization_result)
        assert str(optimizer.pk) in result

    def test_str_contains_pnl(self, optimization_result):
        """__str__ содержит PnL."""
        result = str(optimization_result)
        assert "150" in result


@pytest.mark.django_db
class TestArbitrageTraderOptimizationResultFields:
    """Тесты полей результата оптимизации."""

    def test_high_precision_pnl(self, optimization_result):
        """PnL сохраняется с высокой точностью."""
        assert optimization_result.pnl == Decimal("150.123456789012345678")

    def test_duration_stored(self, optimization_result):
        """duration сохраняется корректно."""
        assert optimization_result.duration == timedelta(minutes=5, seconds=30)

    def test_strategy_arguments_json(self, optimization_result):
        """strategy_arguments — JSON dict."""
        assert optimization_result.strategy_arguments == {
            "open_threshold": 2.0,
            "close_threshold": 0.5,
        }

    def test_multiple_results_for_optimizer(self, optimizer):
        """Один оптимизатор может иметь несколько результатов."""
        for i in range(3):
            ArbitrageTraderOptimizationResult.objects.create(
                optimizer=optimizer,
                duration=timedelta(minutes=i),
                pnl=Decimal(str(100 + i)),
                win_rate=Decimal("0.5"),
                avg_candles_per_position=Decimal("10"),
                pnl_r2=Decimal("0.8"),
                roi=Decimal("10"),
                sharpe=Decimal("1.0"),
                total_positions=5 + i,
                strategy_arguments={},
                risk_manager_arguments={},
            )
        assert (
            ArbitrageTraderOptimizationResult.objects.filter(
                optimizer=optimizer
            ).count()
            == 3
        )


# ==================== ArbitrageTraderOptimizerError ====================


@pytest.mark.django_db
class TestArbitrageTraderOptimizerErrorStr:
    """Тесты __str__ метода."""

    def test_str_contains_type_and_message(self, optimizer_error):
        """__str__ содержит тип и сообщение."""
        result = str(optimizer_error)
        assert "ValueError" in result
        assert "Test optimization error" in result


@pytest.mark.django_db
class TestArbitrageTraderOptimizerErrorFields:
    """Тесты полей ошибки оптимизатора."""

    def test_default_empty_traceback(self, optimizer):
        """traceback по умолчанию пустой."""
        error = ArbitrageTraderOptimizerError.objects.create(
            optimizer=optimizer,
            message="Simple error",
        )
        assert error.traceback == ""

    def test_default_empty_type(self, optimizer):
        """type по умолчанию пустой."""
        error = ArbitrageTraderOptimizerError.objects.create(
            optimizer=optimizer,
            message="Simple error",
        )
        assert error.type == ""

    def test_ordering_newest_first(self, optimizer):
        """Ошибки отсортированы по -created_at (новые первые)."""
        e1 = ArbitrageTraderOptimizerError.objects.create(
            optimizer=optimizer,
            message="Error 1",
        )
        e2 = ArbitrageTraderOptimizerError.objects.create(
            optimizer=optimizer,
            message="Error 2",
        )
        errors = list(ArbitrageTraderOptimizerError.objects.filter(optimizer=optimizer))
        assert errors[0].pk == e2.pk
        assert errors[1].pk == e1.pk

    def test_cascade_delete(self, optimizer_error, optimizer):
        """Удаление оптимизатора каскадно удаляет ошибки."""
        optimizer.delete()
        assert ArbitrageTraderOptimizerError.objects.count() == 0
