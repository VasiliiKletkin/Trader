"""
Тесты моделей Trader.
Фокус на query count validation и корректность ORM операций.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest

from core.utils.types import TraderStatus
from traders.domain import Trader as DomainTrader
from traders.models import (
    Trader,
    TraderPosition,
    TraderSignal,
)

# ==================== Trader Model Tests ====================


@pytest.mark.django_db
class TestTraderModel:
    """Тесты модели Trader."""

    def test_str_representation(self, trader):
        """Тест строкового представления."""
        str_repr = str(trader)
        assert str(trader.pk) in str_repr
        assert "Enabled" in str_repr or "Включен" in str_repr

    def test_timeframe_property(self, trader):
        """Тест свойства timeframe."""
        assert trader.timeframe == trader.candle_source.timeframe

    def test_trading_pair_property(self, trader):
        """Тест свойства trading_pair."""
        assert trader.trading_pair == trader.candle_source.trading_pair

    def test_instantiate_returns_domain_trader(self, trader):
        """Тест что instantiate возвращает domain Trader."""
        domain_trader = trader.instantiate()
        assert isinstance(domain_trader, DomainTrader)
        assert domain_trader.initial_balance == trader.initial_balance

    def test_get_opened_positions(
        self, trader, trader_position, closed_trader_position
    ):
        """Тест получения открытых позиций."""
        opened = trader.get_opened_positions()
        assert opened.count() == 1
        assert trader_position in opened

    def test_get_closed_positions(
        self, trader, trader_position, closed_trader_position
    ):
        """Тест получения закрытых позиций."""
        closed = trader.get_closed_positions()
        assert closed.count() == 1
        assert closed_trader_position in closed

    def test_get_balance_fixed(self, trader):
        """Тест получения баланса при фиксированном балансе."""
        trader.use_fixed_balance = True
        trader.initial_balance = Decimal("1000.00")
        trader.save()

        assert trader.get_balance() == Decimal("1000.00")


@pytest.mark.django_db
class TestTraderPositionModel:
    """Тесты модели TraderPosition."""

    def test_instantiate_returns_domain_position(self, trader_position):
        """Тест что instantiate возвращает domain TraderPosition."""
        domain_position = trader_position.instantiate()
        assert domain_position.open_price == trader_position.open_price
        assert domain_position.amount == trader_position.amount

    def test_pnl_property_opened_position(self, trader_position):
        """Тест PnL для открытой позиции."""
        assert trader_position.pnl is None

    def test_pnl_property_closed_position(self, closed_trader_position):
        """Тест PnL для закрытой позиции."""
        pnl = closed_trader_position.pnl
        expected = (Decimal("52000") - Decimal("50000")) * Decimal("0.1") - Decimal(
            "0.10"
        )
        assert pnl == expected

    def test_is_closed_property(self, trader_position, closed_trader_position):
        """Тест свойства is_closed."""
        assert trader_position.is_closed is False
        assert closed_trader_position.is_closed is True


@pytest.mark.django_db
class TestTraderValidation:
    """Тесты валидации Trader."""

    def test_clean_mismatched_candle_source_exchange(
        self,
        right_candle_source,
        exchange_client,
        strategy,
        risk_manager,
    ):
        """Тест что биржа источника свечей должна совпадать с биржей клиента."""
        from django.forms import ValidationError

        # right_candle_source привязан к Binance, exchange_client — к Bybit
        trader = Trader(
            candle_source=right_candle_source,
            exchange_client=exchange_client,
            strategy=strategy,
            risk_manager=risk_manager,
            initial_balance=Decimal("1000.00"),
        )

        with pytest.raises(ValidationError, match="источника свечей"):
            trader.clean()

    def test_clean_valid_matching_exchange(self, trader):
        """Тест что валидация проходит при совпадении бирж."""
        trader.clean()


@pytest.mark.django_db
class TestTraderClearData:
    """Тесты очистки данных Trader."""

    def test_clear_all_data(self, trader, trader_signal, trader_position):
        """Тест очистки всех данных трейдера."""
        assert TraderSignal.objects.filter(trader=trader).count() > 0
        assert TraderPosition.objects.filter(trader=trader).count() > 0

        trader.clear_all_data()

        assert TraderSignal.objects.filter(trader=trader).count() == 0
        assert TraderPosition.objects.filter(trader=trader).count() == 0


# ==================== Trader Reboot Tests ====================


@pytest.mark.django_db
class TestTraderReboot:
    """Тесты функции reboot трейдера."""

    def test_reboot_skips_if_already_rebooting(self, trader):
        """Тест что reboot пропускается если статус уже REBOOTING."""
        trader.status = TraderStatus.REBOOTING
        trader.save()

        with patch.object(trader, "clear_all_data") as mock_clear:
            trader.reboot()
            mock_clear.assert_not_called()

    def test_reboot_clears_all_data(self, trader, trader_signal, trader_position):
        """Тест что reboot очищает все данные."""
        assert TraderSignal.objects.filter(trader=trader).count() > 0
        assert TraderPosition.objects.filter(trader=trader).count() > 0

        with patch.object(
            trader.candle_source, "get_candle_iterator", return_value=iter([])
        ):
            trader.reboot()

        assert TraderSignal.objects.filter(trader=trader).count() == 0
        assert TraderPosition.objects.filter(trader=trader).count() == 0

    def test_reboot_sets_last_reboot_timestamp(self, trader):
        """Тест что reboot устанавливает last_reboot."""
        assert trader.last_reboot is None

        with patch.object(
            trader.candle_source, "get_candle_iterator", return_value=iter([])
        ):
            trader.reboot()

        trader.refresh_from_db()
        assert trader.last_reboot is not None

    def test_reboot_sets_status_to_paused_on_success(self, trader):
        """Тест что reboot устанавливает статус PAUSED при успехе."""
        trader.status = TraderStatus.ENABLED
        trader.save()

        with patch.object(
            trader.candle_source, "get_candle_iterator", return_value=iter([])
        ):
            trader.reboot()

        trader.refresh_from_db()
        assert trader.status == TraderStatus.PAUSED

    def test_reboot_sets_status_to_error_on_exception(self, trader):
        """Тест что reboot устанавливает статус ERROR при ошибке."""
        trader.status = TraderStatus.ENABLED
        trader.save()

        with patch.object(
            trader.candle_source,
            "get_candle_iterator",
            side_effect=Exception("Test error"),
        ):
            trader.reboot()

        trader.refresh_from_db()
        assert trader.status == TraderStatus.ERROR
        from traders.models import TraderError

        error = TraderError.objects.filter(trader=trader).first()
        assert error is not None
        assert "Test error" in error.message

    def test_reboot_from_enabled_status(self, trader):
        """Тест reboot из статуса ENABLED."""
        trader.status = TraderStatus.ENABLED
        trader.save()

        with patch.object(
            trader.candle_source, "get_candle_iterator", return_value=iter([])
        ):
            trader.reboot()

        trader.refresh_from_db()
        assert trader.status == TraderStatus.PAUSED

    def test_reboot_from_disabled_status(self, trader):
        """Тест reboot из статуса DISABLED."""
        trader.status = TraderStatus.DISABLED
        trader.save()

        with patch.object(
            trader.candle_source, "get_candle_iterator", return_value=iter([])
        ):
            trader.reboot()

        trader.refresh_from_db()
        assert trader.status == TraderStatus.PAUSED
