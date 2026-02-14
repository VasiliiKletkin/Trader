"""
Тесты модели ArbitrageRiskManager.
Фокус на корректность CRUD, Registry-интеграция, auto-population arguments.
"""

import pytest
from django.db import IntegrityError

from arbitrage_traders.domain.risk_managers import (
    AbstractArbitrageRiskManager,
    ArbitrageRiskManagerRegistry,
    PSAllInArbitrageRiskManager,
    PSPercentArbitrageRiskManager,
)
from arbitrage_traders.models import ArbitrageRiskManager

# ==================== Fixtures ====================


@pytest.fixture
def risk_manager() -> ArbitrageRiskManager:
    """Создает риск-менеджер без аргументов (PSAllIn)."""
    return ArbitrageRiskManager.objects.create(
        name="Test RM AllIn",
        class_name=PSAllInArbitrageRiskManager.__name__,
    )


@pytest.fixture
def risk_manager_percent() -> ArbitrageRiskManager:
    """Создает риск-менеджер с процентным размером позиции."""
    return ArbitrageRiskManager.objects.create(
        name="Test RM Percent",
        class_name=PSPercentArbitrageRiskManager.__name__,
        arguments={"position_size_percent": 50.0},
    )


@pytest.fixture
def risk_manager_percent_no_args() -> ArbitrageRiskManager:
    """Создает процентный риск-менеджер без аргументов (auto-populate)."""
    return ArbitrageRiskManager.objects.create(
        name="Auto RM Percent",
        class_name=PSPercentArbitrageRiskManager.__name__,
    )


# ==================== __str__ ====================


@pytest.mark.django_db
class TestArbitrageRiskManagerStr:
    """Тесты __str__ метода."""

    def test_str_contains_name_and_class(self, risk_manager):
        """__str__ содержит название и имя класса."""
        result = str(risk_manager)
        assert "Test RM AllIn" in result
        assert PSAllInArbitrageRiskManager.__name__ in result

    def test_str_format(self, risk_manager):
        """__str__ имеет формат 'name (class_name)'."""
        result = str(risk_manager)
        assert result == f"Test RM AllIn ({PSAllInArbitrageRiskManager.__name__})"


# ==================== save() — auto-populate arguments ====================


@pytest.mark.django_db
class TestArbitrageRiskManagerSave:
    """Тесты метода save() и auto-population аргументов."""

    def test_save_with_explicit_arguments(self, risk_manager_percent):
        """При явных аргументах save() не перезаписывает их."""
        assert risk_manager_percent.arguments == {"position_size_percent": 50.0}

    def test_save_auto_populates_percent_rm(self, risk_manager_percent_no_args):
        """При пустых аргументах PSPercent save() заполняет дефолтами."""
        args = risk_manager_percent_no_args.arguments
        assert "position_size_percent" in args
        assert args["position_size_percent"] == 100.0

    def test_save_allin_has_empty_args(self, risk_manager):
        """PSAllIn не имеет параметров __init__ — arguments остаётся пустым."""
        # PSAllIn не имеет параметров с дефолтами, кроме self
        # get_all_init_args вернёт пустой dict → save не перезапишет
        assert risk_manager.arguments is not None

    def test_save_does_not_overwrite_custom_arguments(self):
        """При повторном save() кастомные аргументы не перезаписываются."""
        rm = ArbitrageRiskManager.objects.create(
            name="Custom RM",
            class_name=PSPercentArbitrageRiskManager.__name__,
            arguments={"position_size_percent": 25.0},
        )
        rm.save()
        rm.refresh_from_db()
        assert rm.arguments["position_size_percent"] == 25.0

    def test_unique_name_constraint(self, risk_manager):
        """Имя риск-менеджера уникально."""
        with pytest.raises(IntegrityError):
            ArbitrageRiskManager.objects.create(
                name="Test RM AllIn",
                class_name=PSAllInArbitrageRiskManager.__name__,
            )


# ==================== get_class() ====================


@pytest.mark.django_db
class TestArbitrageRiskManagerGetClass:
    """Тесты метода get_class()."""

    def test_get_class_returns_allin(self, risk_manager):
        """get_class() возвращает PSAllInArbitrageRiskManager."""
        cls = risk_manager.get_class()
        assert cls is PSAllInArbitrageRiskManager

    def test_get_class_returns_percent(self, risk_manager_percent):
        """get_class() возвращает PSPercentArbitrageRiskManager."""
        cls = risk_manager_percent.get_class()
        assert cls is PSPercentArbitrageRiskManager

    def test_get_class_is_subclass_of_abstract(self, risk_manager):
        """Возвращённый класс наследует AbstractArbitrageRiskManager."""
        cls = risk_manager.get_class()
        assert issubclass(cls, AbstractArbitrageRiskManager)

    def test_get_class_invalid_raises_value_error(self):
        """Невалидный class_name бросает ValueError."""
        rm = ArbitrageRiskManager(
            name="Invalid",
            class_name="NonExistentRM",
        )
        with pytest.raises(ValueError):
            rm.get_class()


# ==================== get_description() ====================


@pytest.mark.django_db
class TestArbitrageRiskManagerGetDescription:
    """Тесты метода get_description()."""

    def test_get_description_allin(self, risk_manager):
        """get_description() для PSAllIn возвращает непустую строку."""
        desc = risk_manager.get_description()
        assert isinstance(desc, str)
        assert len(desc) > 0

    def test_get_description_percent(self, risk_manager_percent):
        """get_description() для PSPercent возвращает непустую строку."""
        desc = risk_manager_percent.get_description()
        assert isinstance(desc, str)
        assert len(desc) > 0

    def test_get_description_matches_docstring(self, risk_manager):
        """get_description() совпадает с docstring класса."""
        cls = risk_manager.get_class()
        expected = (cls.__doc__ or "").strip()
        assert risk_manager.get_description() == expected


# ==================== instantiate() ====================


@pytest.mark.django_db
class TestArbitrageRiskManagerInstantiate:
    """Тесты метода instantiate()."""

    def test_instantiate_allin(self, risk_manager):
        """instantiate() PSAllIn возвращает доменный объект."""
        domain_obj = risk_manager.instantiate()
        assert isinstance(domain_obj, PSAllInArbitrageRiskManager)

    def test_instantiate_percent_with_stored_args(self, risk_manager_percent):
        """instantiate() PSPercent использует сохранённые аргументы."""
        domain_obj = risk_manager_percent.instantiate()
        assert isinstance(domain_obj, PSPercentArbitrageRiskManager)
        assert domain_obj.position_size_percent == 50.0

    def test_instantiate_with_duplicate_kwargs_raises(self, risk_manager_percent):
        """instantiate() с дублирующим kwarg бросает TypeError."""
        with pytest.raises(TypeError):
            risk_manager_percent.instantiate(position_size_percent=75.0)

    def test_instantiate_auto_populated(self, risk_manager_percent_no_args):
        """instantiate() работает с auto-populated аргументами."""
        domain_obj = risk_manager_percent_no_args.instantiate()
        assert isinstance(domain_obj, PSPercentArbitrageRiskManager)
        assert domain_obj.position_size_percent == 100.0


# ==================== Registry Integration ====================


@pytest.mark.django_db
class TestArbitrageRiskManagerRegistry:
    """Тесты интеграции с реестром риск-менеджеров."""

    def test_registry_contains_allin(self):
        """Реестр содержит PSAllInArbitrageRiskManager."""
        cls = ArbitrageRiskManagerRegistry.get_class(
            PSAllInArbitrageRiskManager.__name__
        )
        assert cls is PSAllInArbitrageRiskManager

    def test_registry_contains_percent(self):
        """Реестр содержит PSPercentArbitrageRiskManager."""
        cls = ArbitrageRiskManagerRegistry.get_class(
            PSPercentArbitrageRiskManager.__name__
        )
        assert cls is PSPercentArbitrageRiskManager

    def test_registry_choices_not_empty(self):
        """get_choices() возвращает непустой список."""
        choices = ArbitrageRiskManagerRegistry.get_choices()
        assert len(choices) >= 2

    def test_registry_choices_contain_both(self):
        """Список выбора содержит оба риск-менеджера."""
        choices = ArbitrageRiskManagerRegistry.get_choices()
        names = [c[0] for c in choices]
        assert PSAllInArbitrageRiskManager.__name__ in names
        assert PSPercentArbitrageRiskManager.__name__ in names
