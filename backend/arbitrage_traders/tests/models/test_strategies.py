"""
Тесты модели ArbitrageStrategy.
Фокус на корректность CRUD, Registry-интеграция, auto-population arguments.
"""

import pytest
from django.db import IntegrityError

from arbitrage_traders.domain.strategies import (
    AbstractArbitrageStrategy,
    ArbitrageStrategyRegistry,
    SpreadReversionArbitrageStrategy,
)
from arbitrage_traders.models import ArbitrageStrategy

# ==================== Fixtures ====================


@pytest.fixture
def strategy() -> ArbitrageStrategy:
    """Создает арбитражную стратегию с явными аргументами."""
    return ArbitrageStrategy.objects.create(
        name="Test Strategy",
        class_name=SpreadReversionArbitrageStrategy.__name__,
        arguments={"open_threshold": 0.01, "close_threshold": 0.002},
    )


@pytest.fixture
def strategy_no_args() -> ArbitrageStrategy:
    """Создает арбитражную стратегию без аргументов (auto-populate)."""
    return ArbitrageStrategy.objects.create(
        name="Auto Args Strategy",
        class_name=SpreadReversionArbitrageStrategy.__name__,
    )


# ==================== __str__ ====================


@pytest.mark.django_db
class TestArbitrageStrategyStr:
    """Тесты __str__ метода."""

    def test_str_contains_name_and_class(self, strategy):
        """__str__ содержит название и имя класса."""
        result = str(strategy)
        assert "Test Strategy" in result
        assert SpreadReversionArbitrageStrategy.__name__ in result

    def test_str_format(self, strategy):
        """__str__ имеет формат 'name (class_name)'."""
        result = str(strategy)
        assert result == f"Test Strategy ({SpreadReversionArbitrageStrategy.__name__})"


# ==================== save() — auto-populate arguments ====================


@pytest.mark.django_db
class TestArbitrageStrategySave:
    """Тесты метода save() и auto-population аргументов."""

    def test_save_with_explicit_arguments(self, strategy):
        """При явных аргументах save() не перезаписывает их."""
        assert strategy.arguments == {"open_threshold": 0.01, "close_threshold": 0.002}

    def test_save_auto_populates_empty_arguments(self, strategy_no_args):
        """При пустых аргументах save() заполняет дефолтами из класса."""
        assert strategy_no_args.arguments != {}
        assert "open_threshold" in strategy_no_args.arguments
        assert "close_threshold" in strategy_no_args.arguments

    def test_save_auto_populated_values_match_defaults(self, strategy_no_args):
        """Auto-populated значения соответствуют дефолтам __init__."""
        assert strategy_no_args.arguments["open_threshold"] == 0.01
        assert strategy_no_args.arguments["close_threshold"] == 0.002

    def test_save_does_not_overwrite_custom_arguments(self):
        """При повторном save() кастомные аргументы не перезаписываются."""
        strategy = ArbitrageStrategy.objects.create(
            name="Custom Args",
            class_name=SpreadReversionArbitrageStrategy.__name__,
            arguments={"open_threshold": 0.05, "close_threshold": 0.01},
        )
        strategy.save()
        strategy.refresh_from_db()
        assert strategy.arguments["open_threshold"] == 0.05
        assert strategy.arguments["close_threshold"] == 0.01

    def test_unique_name_constraint(self, strategy):
        """Имя стратегии уникально."""
        with pytest.raises(IntegrityError):
            ArbitrageStrategy.objects.create(
                name="Test Strategy",
                class_name=SpreadReversionArbitrageStrategy.__name__,
            )


# ==================== get_class() ====================


@pytest.mark.django_db
class TestArbitrageStrategyGetClass:
    """Тесты метода get_class()."""

    def test_get_class_returns_correct_type(self, strategy):
        """get_class() возвращает правильный класс стратегии."""
        cls = strategy.get_class()
        assert cls is SpreadReversionArbitrageStrategy

    def test_get_class_is_subclass_of_abstract(self, strategy):
        """Возвращённый класс наследует AbstractArbitrageStrategy."""
        cls = strategy.get_class()
        assert issubclass(cls, AbstractArbitrageStrategy)

    def test_get_class_invalid_raises_value_error(self):
        """Невалидный class_name бросает ValueError."""
        strategy = ArbitrageStrategy(
            name="Invalid",
            class_name="NonExistentStrategy",
        )
        with pytest.raises(ValueError):
            strategy.get_class()


# ==================== get_description() ====================


@pytest.mark.django_db
class TestArbitrageStrategyGetDescription:
    """Тесты метода get_description()."""

    def test_get_description_returns_string(self, strategy):
        """get_description() возвращает непустую строку для стратегии с docstring."""
        desc = strategy.get_description()
        assert isinstance(desc, str)
        assert len(desc) > 0

    def test_get_description_matches_class_docstring(self, strategy):
        """get_description() совпадает с docstring класса."""
        cls = strategy.get_class()
        expected = (cls.__doc__ or "").strip()
        assert strategy.get_description() == expected


# ==================== instantiate() ====================


@pytest.mark.django_db
class TestArbitrageStrategyInstantiate:
    """Тесты метода instantiate()."""

    def test_instantiate_returns_domain_object(self, strategy):
        """instantiate() возвращает экземпляр доменного класса."""
        domain_obj = strategy.instantiate()
        assert isinstance(domain_obj, SpreadReversionArbitrageStrategy)

    def test_instantiate_with_stored_arguments(self, strategy):
        """instantiate() использует сохранённые аргументы."""
        domain_obj = strategy.instantiate()
        assert domain_obj.open_threshold == 0.01
        assert domain_obj.close_threshold == 0.002

    def test_instantiate_with_duplicate_kwargs_raises(self, strategy):
        """instantiate() с дублирующим kwarg бросает TypeError."""
        with pytest.raises(TypeError):
            strategy.instantiate(open_threshold=3.0)

    def test_instantiate_auto_populated_args(self, strategy_no_args):
        """instantiate() работает с auto-populated аргументами."""
        domain_obj = strategy_no_args.instantiate()
        assert isinstance(domain_obj, SpreadReversionArbitrageStrategy)
        assert domain_obj.open_threshold == 0.01


# ==================== Registry Integration ====================


@pytest.mark.django_db
class TestArbitrageStrategyRegistry:
    """Тесты интеграции с реестром стратегий."""

    def test_registry_contains_simple_strategy(self):
        """Реестр содержит SpreadReversionArbitrageStrategy."""
        cls = ArbitrageStrategyRegistry.get_class(
            SpreadReversionArbitrageStrategy.__name__
        )
        assert cls is SpreadReversionArbitrageStrategy

    def test_registry_choices_not_empty(self):
        """get_choices() возвращает непустой список."""
        choices = ArbitrageStrategyRegistry.get_choices()
        assert len(choices) > 0

    def test_registry_choices_contain_simple(self):
        """Список выбора содержит SpreadReversionArbitrageStrategy."""
        choices = ArbitrageStrategyRegistry.get_choices()
        names = [c[0] for c in choices]
        assert SpreadReversionArbitrageStrategy.__name__ in names
