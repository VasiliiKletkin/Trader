"""
Тесты моделей ArbitrageTrader.
Фокус на query count validation и корректность ORM операций.
"""

from collections import deque
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from candle_sources.domain import ProviderCandle
from core.utils.types import (
    OrderSide,
    OrderStatus,
    PositionStatus,
    PositionType,
    SignalType,
    TraderStatus,
)
from exchange_clients.domain import ExchangeClientOrder, OrderType
from exchange_clients.models import ExchangeClientOrder as ExchangeClientOrderModel
from exchanges.domain import ExchangeCandle as DomainExchangeCandle
from exchanges.domain import TradingPair as DomainTradingPair
from strategies.domain.schemas import (
    ArbitrageTraderSignal as DomainArbitrageTraderSignal,
)
from traders.domain import ArbitrageTrader as DomainArbitrageTrader
from traders.domain.schemas import (
    ArbitrageTraderError as DomainArbitrageTraderError,
)
from traders.domain.schemas import (
    ArbitrageTraderPosition as DomainArbitrageTraderPosition,
)
from traders.models import (
    ArbitrageTrader,
    ArbitrageTraderError,
    ArbitrageTraderPosition,
    ArbitrageTraderSignal,
)

# ==================== ArbitrageTrader Model Tests ====================


@pytest.mark.django_db
class TestArbitrageTraderModel:
    """Тесты модели ArbitrageTrader."""

    def test_str_representation(self, arbitrage_trader):
        """Тест строкового представления."""
        str_repr = str(arbitrage_trader)
        assert str(arbitrage_trader.pk) in str_repr

    def test_timeframe_property(self, arbitrage_trader):
        """Тест свойства timeframe."""
        assert (
            arbitrage_trader.timeframe == arbitrage_trader.first_candle_source.timeframe
        )

    def test_trading_pair_property(self, arbitrage_trader):
        """Тест свойства trading_pair."""
        assert (
            arbitrage_trader.trading_pair
            == arbitrage_trader.first_candle_source.trading_pair
        )

    def test_instantiate_returns_domain_trader(self, arbitrage_trader):
        """Тест что instantiate возвращает domain ArbitrageTrader."""
        domain_trader = arbitrage_trader.instantiate()
        assert isinstance(domain_trader, DomainArbitrageTrader)
        assert domain_trader.initial_balance == arbitrage_trader.initial_balance

    def test_get_opened_positions(
        self, arbitrage_trader, arbitrage_position, closed_arbitrage_position
    ):
        """Тест получения открытых позиций."""
        opened = arbitrage_trader.get_opened_positions()
        assert opened.count() == 1
        assert arbitrage_position in opened

    def test_get_closed_positions(
        self, arbitrage_trader, arbitrage_position, closed_arbitrage_position
    ):
        """Тест получения закрытых позиций."""
        closed = arbitrage_trader.get_closed_positions()
        assert closed.count() == 1
        assert closed_arbitrage_position in closed

    def test_get_balance_fixed(self, arbitrage_trader):
        """Тест получения баланса при фиксированном балансе."""
        arbitrage_trader.use_fixed_balance = True
        arbitrage_trader.initial_balance = Decimal("1000.00")
        arbitrage_trader.save()

        assert arbitrage_trader.get_balance() == Decimal("1000.00")


@pytest.mark.django_db
class TestArbitrageTraderPositionModel:
    """Тесты модели ArbitrageTraderPosition."""

    def test_instantiate_returns_domain_position(self, arbitrage_position):
        """Тест что instantiate возвращает domain ArbitrageTraderPosition."""
        domain_position = arbitrage_position.instantiate()
        assert domain_position.first_open_price == arbitrage_position.first_open_price
        assert domain_position.second_open_price == arbitrage_position.second_open_price

    def test_pnl_property_opened_position(self, arbitrage_position):
        """Тест PnL для открытой позиции."""
        assert arbitrage_position.pnl is None

    def test_pnl_property_closed_position(self, closed_arbitrage_position):
        """Тест PnL для закрытой позиции."""
        pnl = closed_arbitrage_position.pnl
        assert pnl is not None
        assert pnl > 0

    def test_is_closed_property(self, arbitrage_position, closed_arbitrage_position):
        """Тест свойства is_closed."""
        assert arbitrage_position.is_closed is False
        assert closed_arbitrage_position.is_closed is True

    def test_open_cost_property(self, closed_arbitrage_position):
        """Тест свойства open_cost."""
        open_cost = closed_arbitrage_position.open_cost
        expected = (Decimal("50000") + Decimal("50100")) * Decimal("0.1")
        assert open_cost == expected

    def test_close_cost_property(self, closed_arbitrage_position):
        """Тест свойства close_cost."""
        close_cost = closed_arbitrage_position.close_cost
        expected = (Decimal("50500") + Decimal("49800")) * Decimal("0.1")
        assert close_cost == expected


@pytest.mark.django_db
class TestArbitrageTraderClearData:
    """Тесты очистки данных ArbitrageTrader."""

    def test_clear_all_data(
        self, arbitrage_trader, arbitrage_signal, arbitrage_position
    ):
        """Тест очистки всех данных арбитражного трейдера."""
        assert ArbitrageTraderSignal.objects.filter(trader=arbitrage_trader).count() > 0
        assert (
            ArbitrageTraderPosition.objects.filter(trader=arbitrage_trader).count() > 0
        )

        arbitrage_trader.clear_all_data()

        assert (
            ArbitrageTraderSignal.objects.filter(trader=arbitrage_trader).count() == 0
        )
        assert (
            ArbitrageTraderPosition.objects.filter(trader=arbitrage_trader).count() == 0
        )


@pytest.mark.django_db
class TestArbitrageTraderErrorModel:
    """Тесты модели ArbitrageTraderError."""

    def test_create_error(self, arbitrage_trader):
        """Тест создания ошибки."""
        error = ArbitrageTraderError.objects.create(
            trader=arbitrage_trader,
            message="Test error message",
            type="TestError",
            traceback="Traceback...",
        )

        assert error.trader == arbitrage_trader
        assert error.message == "Test error message"
        assert error.type == "TestError"

    def test_str_representation(self, arbitrage_trader):
        """Тест строкового представления."""
        error = ArbitrageTraderError.objects.create(
            trader=arbitrage_trader,
            message="Test error",
            type="TestError",
        )
        str_repr = str(error)
        assert str(arbitrage_trader.pk) in str_repr
        assert "TestError" in str_repr

    def test_instantiate_returns_domain_error(self, arbitrage_trader):
        """Тест что instantiate возвращает domain error."""
        error = ArbitrageTraderError.objects.create(
            trader=arbitrage_trader,
            message="Test error",
            type="TestError",
        )
        domain_error = error.instantiate()
        assert domain_error.message == error.message
        assert domain_error.type == error.type


@pytest.mark.django_db
class TestArbitrageTraderValidation:
    """Тесты валидации ArbitrageTrader."""

    def test_clean_same_exchange_clients_raises_error(
        self,
        candle_source,
        second_candle_source,
        exchange_client,
        arbitrage_strategy,
        arbitrage_risk_manager,
    ):
        """Тест что нельзя создать трейдера с одинаковыми клиентами."""
        from django.forms import ValidationError

        trader = ArbitrageTrader(
            first_candle_source=candle_source,
            second_candle_source=second_candle_source,
            first_exchange_client=exchange_client,
            second_exchange_client=exchange_client,
            strategy=arbitrage_strategy,
            risk_manager=arbitrage_risk_manager,
            initial_balance=Decimal("1000.00"),
        )

        with pytest.raises(ValidationError):
            trader.clean()

    def test_clean_mismatched_first_candle_source_exchange(
        self,
        candle_source,
        second_candle_source,
        exchange_client,
        second_exchange_client,
        arbitrage_strategy,
        arbitrage_risk_manager,
    ):
        """Тест что биржа первого источника свечей должна совпадать с биржей первого клиента."""
        from django.forms import ValidationError

        # first_candle_source привязан к exchange_client (Bybit),
        # но first_exchange_client = second_exchange_client (Binance)
        trader = ArbitrageTrader(
            first_candle_source=candle_source,
            second_candle_source=second_candle_source,
            first_exchange_client=second_exchange_client,
            second_exchange_client=exchange_client,
            strategy=arbitrage_strategy,
            risk_manager=arbitrage_risk_manager,
            initial_balance=Decimal("1000.00"),
        )

        with pytest.raises(ValidationError, match="первого источника свечей"):
            trader.clean()

    def test_clean_mismatched_second_candle_source_exchange(
        self,
        candle_source,
        second_candle_source,
        exchange_client,
        second_exchange_client,
        arbitrage_strategy,
        arbitrage_risk_manager,
        exchange,
        second_exchange,
    ):
        """Тест что биржа второго источника свечей должна совпадать с биржей второго клиента."""
        from django.forms import ValidationError

        from exchange_clients.domain.exchange_clients import (
            KrakenExchangeClient,
        )
        from exchange_clients.models import ExchangeClient as ExchangeClientModel
        from exchanges.models import Exchange

        # Создаем третью биржу и клиента
        third_exchange, _ = Exchange.objects.get_or_create(
            class_name=KrakenExchangeClient.__name__,
            defaults={"name": "Kraken Test"},
        )
        third_exchange_client = ExchangeClientModel.objects.create(
            exchange=third_exchange,
            api_key="test_key_3",
            api_secret="test_secret_3",
            name="Test Client 3",
            demo=True,
        )

        # first совпадает, second не совпадает
        trader = ArbitrageTrader(
            first_candle_source=candle_source,
            second_candle_source=second_candle_source,
            first_exchange_client=exchange_client,
            second_exchange_client=third_exchange_client,
            strategy=arbitrage_strategy,
            risk_manager=arbitrage_risk_manager,
            initial_balance=Decimal("1000.00"),
        )

        with pytest.raises(ValidationError, match="второго источника свечей"):
            trader.clean()

    def test_clean_valid_matching_exchanges(self, arbitrage_trader):
        """Тест что валидация проходит при совпадении бирж."""
        # arbitrage_trader создан с правильными парами - не должно быть ошибок
        arbitrage_trader.clean()


@pytest.mark.django_db
class TestArbitrageTraderQueryOptimization:
    """Тесты оптимизации запросов для ArbitrageTrader."""

    def test_load_positions_query_count(self, arbitrage_trader, arbitrage_position):
        """Тест количества запросов при загрузке позиций."""
        for i in range(3):
            ArbitrageTraderPosition.objects.create(
                trader=arbitrage_trader,
                type=PositionType.LONG,
                first_type=PositionType.LONG,
                second_type=PositionType.SHORT,
                status=PositionStatus.OPENED,
                amount=Decimal("0.1"),
                first_open_price=Decimal("50000.00") + i * 100,
                second_open_price=Decimal("50100.00") + i * 100,
                opened_at=datetime.now(UTC) + timedelta(hours=i),
                total_fee=Decimal("0.10"),
            )

        domain_trader = arbitrage_trader.instantiate()

        with CaptureQueriesContext(connection) as queries:
            arbitrage_trader.load(domain_trader)

        # Должно быть 2 запроса: сигналы и позиции
        assert len(queries) == 2


# ==================== ArbitrageTrader Reboot Tests ====================


@pytest.mark.django_db
class TestArbitrageTraderReboot:
    """Тесты функции reboot арбитражного трейдера."""

    def test_reboot_skips_if_already_rebooting(self, arbitrage_trader):
        """Тест что reboot пропускается если статус уже REBOOTING."""
        arbitrage_trader.status = TraderStatus.REBOOTING
        arbitrage_trader.save()

        with patch.object(arbitrage_trader, "clear_all_data") as mock_clear:
            arbitrage_trader.reboot()
            mock_clear.assert_not_called()

    def test_reboot_clears_all_data(
        self, arbitrage_trader, arbitrage_signal, arbitrage_position
    ):
        """Тест что reboot очищает все данные."""
        assert ArbitrageTraderSignal.objects.filter(trader=arbitrage_trader).count() > 0
        assert (
            ArbitrageTraderPosition.objects.filter(trader=arbitrage_trader).count() > 0
        )

        with patch.object(
            arbitrage_trader, "get_candle_iterator", return_value=iter([])
        ):
            arbitrage_trader.reboot()

        assert (
            ArbitrageTraderSignal.objects.filter(trader=arbitrage_trader).count() == 0
        )
        assert (
            ArbitrageTraderPosition.objects.filter(trader=arbitrage_trader).count() == 0
        )

    def test_reboot_sets_last_reboot_timestamp(self, arbitrage_trader):
        """Тест что reboot устанавливает last_reboot."""
        assert arbitrage_trader.last_reboot is None

        with patch.object(
            arbitrage_trader, "get_candle_iterator", return_value=iter([])
        ):
            arbitrage_trader.reboot()

        arbitrage_trader.refresh_from_db()
        assert arbitrage_trader.last_reboot is not None

    def test_reboot_sets_status_to_paused_on_success(self, arbitrage_trader):
        """Тест что reboot устанавливает статус PAUSED при успехе."""
        arbitrage_trader.status = TraderStatus.ENABLED
        arbitrage_trader.save()

        with patch.object(
            arbitrage_trader, "get_candle_iterator", return_value=iter([])
        ):
            arbitrage_trader.reboot()

        arbitrage_trader.refresh_from_db()
        assert arbitrage_trader.status == TraderStatus.PAUSED

    def test_reboot_sets_status_to_error_on_exception(self, arbitrage_trader):
        """Тест что reboot устанавливает статус ERROR при ошибке."""
        arbitrage_trader.status = TraderStatus.ENABLED
        arbitrage_trader.save()

        with patch.object(
            arbitrage_trader,
            "get_candle_iterator",
            side_effect=Exception("Test error"),
        ):
            arbitrage_trader.reboot()

        arbitrage_trader.refresh_from_db()
        assert arbitrage_trader.status == TraderStatus.ERROR
        assert ArbitrageTraderError.objects.filter(
            trader=arbitrage_trader, message__contains="Test error"
        ).exists()

    def test_reboot_creates_error_record_on_exception(self, arbitrage_trader):
        """Тест что reboot создает запись об ошибке при исключении."""
        initial_error_count = ArbitrageTraderError.objects.filter(
            trader=arbitrage_trader
        ).count()

        with patch.object(
            arbitrage_trader,
            "get_candle_iterator",
            side_effect=ValueError("Specific error"),
        ):
            arbitrage_trader.reboot()

        assert (
            ArbitrageTraderError.objects.filter(trader=arbitrage_trader).count()
            == initial_error_count + 1
        )
        error = ArbitrageTraderError.objects.filter(trader=arbitrage_trader).last()
        assert "Specific error" in error.message
        assert error.type == "ValueError"

    def test_reboot_from_enabled_status(self, arbitrage_trader):
        """Тест reboot из статуса ENABLED."""
        arbitrage_trader.status = TraderStatus.ENABLED
        arbitrage_trader.save()

        with patch.object(
            arbitrage_trader, "get_candle_iterator", return_value=iter([])
        ):
            arbitrage_trader.reboot()

        arbitrage_trader.refresh_from_db()
        assert arbitrage_trader.status == TraderStatus.PAUSED

    def test_reboot_from_disabled_status(self, arbitrage_trader):
        """Тест reboot из статуса DISABLED."""
        arbitrage_trader.status = TraderStatus.DISABLED
        arbitrage_trader.save()

        with patch.object(
            arbitrage_trader, "get_candle_iterator", return_value=iter([])
        ):
            arbitrage_trader.reboot()

        arbitrage_trader.refresh_from_db()
        assert arbitrage_trader.status == TraderStatus.PAUSED


# ==================== ArbitrageTrader Sync Tests ====================


@pytest.fixture
def domain_candle(exchange_candle, second_exchange_candle):
    """Создает domain ProviderCandle для тестов."""
    first = DomainExchangeCandle(
        id=exchange_candle.id,
        dt_unix=int(exchange_candle.timestamp.timestamp() * 1000),
        open=exchange_candle.open,
        high=exchange_candle.high,
        low=exchange_candle.low,
        close=exchange_candle.close,
        volume=exchange_candle.volume,
    )
    second = DomainExchangeCandle(
        id=second_exchange_candle.id,
        dt_unix=int(second_exchange_candle.timestamp.timestamp() * 1000),
        open=second_exchange_candle.open,
        high=second_exchange_candle.high,
        low=second_exchange_candle.low,
        close=second_exchange_candle.close,
        volume=second_exchange_candle.volume,
    )
    return ProviderCandle(
        dt_unix=first.dt_unix,
        open=first.open,
        high=first.high,
        low=first.low,
        close=first.close,
        volume=first.volume,
        first_candle=first,
        second_candle=second,
    )


@pytest.fixture
def domain_signal(domain_candle):
    """Создает domain ArbitrageTraderSignal для тестов."""
    return DomainArbitrageTraderSignal(
        timestamp=datetime.now(UTC),
        first_type=SignalType.BUY,
        second_type=SignalType.SELL,
        first_price=Decimal("50000.00"),
        second_price=Decimal("50100.00"),
        candle=domain_candle,
        data={},
    )


@pytest.fixture
def domain_trading_pair():
    """Создает domain TradingPair для тестов."""
    return DomainTradingPair(
        name="BTC/USDT",
        symbol="BTC/USDT:USDT",
        min_amount=Decimal("0.001"),
        max_amount=Decimal("1000"),
        fee_percent=Decimal("0.1"),
    )


@pytest.fixture
def domain_order(domain_trading_pair):
    """Создает domain ExchangeClientOrder для тестов."""
    return ExchangeClientOrder(
        exchange_order_id="test-order-123",
        status=OrderStatus.CLOSED,
        type=OrderType.MARKET,
        trading_pair=domain_trading_pair,
        side=OrderSide.BUY,
        timestamp=datetime.now(UTC),
        amount=Decimal("0.1"),
        price=Decimal("50000.00"),
        cost=Decimal("5000.00"),
        fee=Decimal("5.00"),
    )


@pytest.fixture
def domain_position(domain_trading_pair):
    """Создает domain ArbitrageTraderPosition для тестов."""
    first_order = ExchangeClientOrder(
        exchange_order_id="first-order-123",
        status=OrderStatus.CLOSED,
        type=OrderType.MARKET,
        trading_pair=domain_trading_pair,
        side=OrderSide.BUY,
        timestamp=datetime.now(UTC),
        amount=Decimal("0.1"),
        price=Decimal("50000.00"),
        cost=Decimal("5000.00"),
        fee=Decimal("5.00"),
    )
    second_order = ExchangeClientOrder(
        exchange_order_id="second-order-123",
        status=OrderStatus.CLOSED,
        type=OrderType.MARKET,
        trading_pair=domain_trading_pair,
        side=OrderSide.SELL,
        timestamp=datetime.now(UTC),
        amount=Decimal("0.1"),
        price=Decimal("50100.00"),
        cost=Decimal("5010.00"),
        fee=Decimal("5.01"),
    )
    return DomainArbitrageTraderPosition(
        type=PositionType.LONG,
        first_type=PositionType.LONG,
        second_type=PositionType.SHORT,
        status=PositionStatus.OPENED,
        amount=Decimal("0.1"),
        first_open_price=Decimal("50000.00"),
        second_open_price=Decimal("50100.00"),
        opened_at=datetime.now(UTC),
        total_fee=Decimal("10.01"),
        first_orders=[first_order],
        second_orders=[second_order],
    )


@pytest.fixture
def domain_error():
    """Создает domain ArbitrageTraderError для тестов."""
    return DomainArbitrageTraderError(
        timestamp=datetime.now(UTC),
        message="Test error message",
        type="TestError",
        traceback="Traceback...",
    )


@pytest.mark.django_db
class TestArbitrageTraderSyncSignals:
    """Тесты метода sync_signals."""

    def test_sync_signals_creates_signals(
        self, arbitrage_trader, domain_signal, exchange_candle, second_exchange_candle
    ):
        """Тест что sync_signals создает сигналы в БД."""
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.signals = deque([domain_signal])

        initial_count = ArbitrageTraderSignal.objects.filter(
            trader=arbitrage_trader
        ).count()

        arbitrage_trader.sync_signals(trader=domain_trader)

        assert (
            ArbitrageTraderSignal.objects.filter(trader=arbitrage_trader).count()
            == initial_count + 1
        )
        saved_signal = ArbitrageTraderSignal.objects.filter(
            trader=arbitrage_trader
        ).last()
        assert saved_signal.first_type == SignalType.BUY
        assert saved_signal.second_type == SignalType.SELL
        assert saved_signal.first_price == Decimal("50000.00")
        assert saved_signal.second_price == Decimal("50100.00")

    def test_sync_signals_skips_existing_signals(
        self, arbitrage_trader, domain_signal, arbitrage_signal
    ):
        """Тест что sync_signals не дублирует сигналы с id."""
        domain_signal.id = arbitrage_signal.id
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.signals = deque([domain_signal])

        initial_count = ArbitrageTraderSignal.objects.filter(
            trader=arbitrage_trader
        ).count()

        arbitrage_trader.sync_signals(trader=domain_trader)

        assert (
            ArbitrageTraderSignal.objects.filter(trader=arbitrage_trader).count()
            == initial_count
        )

    def test_sync_signals_with_empty_signals(self, arbitrage_trader):
        """Тест sync_signals с пустым списком сигналов."""
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.signals = deque()

        initial_count = ArbitrageTraderSignal.objects.filter(
            trader=arbitrage_trader
        ).count()

        arbitrage_trader.sync_signals(trader=domain_trader)

        assert (
            ArbitrageTraderSignal.objects.filter(trader=arbitrage_trader).count()
            == initial_count
        )


@pytest.mark.django_db
class TestArbitrageTraderSyncPositions:
    """Тесты метода sync_positions."""

    def test_sync_positions_creates_positions(self, arbitrage_trader, domain_position):
        """Тест что sync_positions создает позиции в БД."""
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.positions = [domain_position]

        initial_count = ArbitrageTraderPosition.objects.filter(
            trader=arbitrage_trader
        ).count()

        arbitrage_trader.sync_positions(trader=domain_trader)

        assert (
            ArbitrageTraderPosition.objects.filter(trader=arbitrage_trader).count()
            == initial_count + 1
        )
        saved_position = ArbitrageTraderPosition.objects.filter(
            trader=arbitrage_trader
        ).last()
        assert saved_position.type == PositionType.LONG
        assert saved_position.first_type == PositionType.LONG
        assert saved_position.second_type == PositionType.SHORT
        assert saved_position.amount == Decimal("0.1")

    def test_sync_positions_with_empty_positions(self, arbitrage_trader):
        """Тест sync_positions с пустым списком позиций."""
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.positions = []

        initial_count = ArbitrageTraderPosition.objects.filter(
            trader=arbitrage_trader
        ).count()

        arbitrage_trader.sync_positions(trader=domain_trader)

        assert (
            ArbitrageTraderPosition.objects.filter(trader=arbitrage_trader).count()
            == initial_count
        )


@pytest.mark.django_db
class TestArbitrageTraderSyncOrders:
    """Тесты метода sync_orders."""

    def test_sync_orders_creates_orders(self, arbitrage_trader, domain_position):
        """Тест что sync_orders создает ордера в БД."""
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.positions = [domain_position]

        initial_count = ExchangeClientOrderModel.objects.count()

        arbitrage_trader.sync_orders(trader=domain_trader)

        # Должно быть создано 2 ордера (first + second)
        assert ExchangeClientOrderModel.objects.count() == initial_count + 2

    def test_sync_orders_with_empty_orders(self, arbitrage_trader):
        """Тест sync_orders с пустым списком ордеров."""
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.positions = []

        initial_count = ExchangeClientOrderModel.objects.count()

        arbitrage_trader.sync_orders(trader=domain_trader)

        assert ExchangeClientOrderModel.objects.count() == initial_count


@pytest.mark.django_db
class TestArbitrageTraderSyncErrors:
    """Тесты метода sync_errors."""

    def test_sync_errors_creates_errors(self, arbitrage_trader, domain_error):
        """Тест что sync_errors создает ошибки в БД."""
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.errors = [domain_error]

        initial_count = ArbitrageTraderError.objects.filter(
            trader=arbitrage_trader
        ).count()

        with patch("traders.models.send_notification.delay"):
            arbitrage_trader.sync_errors(trader=domain_trader)

        assert (
            ArbitrageTraderError.objects.filter(trader=arbitrage_trader).count()
            == initial_count + 1
        )
        saved_error = ArbitrageTraderError.objects.filter(
            trader=arbitrage_trader
        ).last()
        assert saved_error.message == "Test error message"
        assert saved_error.type == "TestError"

    def test_sync_errors_sets_trader_status_to_error(
        self, arbitrage_trader, domain_error
    ):
        """Тест что sync_errors устанавливает статус ERROR."""
        arbitrage_trader.status = TraderStatus.ENABLED
        arbitrage_trader.save()

        domain_trader = arbitrage_trader.instantiate()
        domain_trader.errors = [domain_error]

        with patch("traders.models.send_notification.delay"):
            arbitrage_trader.sync_errors(trader=domain_trader)

        arbitrage_trader.refresh_from_db()
        assert arbitrage_trader.status == TraderStatus.ERROR

    def test_sync_errors_with_empty_errors(self, arbitrage_trader):
        """Тест sync_errors с пустым списком ошибок."""
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.errors = []

        initial_count = ArbitrageTraderError.objects.filter(
            trader=arbitrage_trader
        ).count()

        arbitrage_trader.sync_errors(trader=domain_trader)

        assert (
            ArbitrageTraderError.objects.filter(trader=arbitrage_trader).count()
            == initial_count
        )

    def test_sync_errors_skips_existing_errors(self, arbitrage_trader, domain_error):
        """Тест что sync_errors не дублирует ошибки с id."""
        existing_error = ArbitrageTraderError.objects.create(
            trader=arbitrage_trader,
            message="Existing error",
            type="ExistingError",
        )
        domain_error.id = existing_error.id

        domain_trader = arbitrage_trader.instantiate()
        domain_trader.errors = [domain_error]

        initial_count = ArbitrageTraderError.objects.filter(
            trader=arbitrage_trader
        ).count()

        arbitrage_trader.sync_errors(trader=domain_trader)

        assert (
            ArbitrageTraderError.objects.filter(trader=arbitrage_trader).count()
            == initial_count
        )


@pytest.mark.django_db
class TestArbitrageTraderSyncFull:
    """Тесты полного цикла sync."""

    def test_sync_creates_all_entities(
        self,
        arbitrage_trader,
        domain_signal,
        domain_position,
        domain_error,
        exchange_candle,
        second_exchange_candle,
    ):
        """Тест что sync создает все сущности в БД."""
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.signals = deque([domain_signal])
        domain_trader.positions = [domain_position]
        domain_trader.errors = [domain_error]

        initial_signals = ArbitrageTraderSignal.objects.filter(
            trader=arbitrage_trader
        ).count()
        initial_positions = ArbitrageTraderPosition.objects.filter(
            trader=arbitrage_trader
        ).count()
        initial_errors = ArbitrageTraderError.objects.filter(
            trader=arbitrage_trader
        ).count()
        initial_orders = ExchangeClientOrderModel.objects.count()

        with patch("traders.models.send_notification.delay"):
            arbitrage_trader.sync(trader=domain_trader)

        assert (
            ArbitrageTraderSignal.objects.filter(trader=arbitrage_trader).count()
            == initial_signals + 1
        )
        assert (
            ArbitrageTraderPosition.objects.filter(trader=arbitrage_trader).count()
            == initial_positions + 1
        )
        assert (
            ArbitrageTraderError.objects.filter(trader=arbitrage_trader).count()
            == initial_errors + 1
        )
        assert ExchangeClientOrderModel.objects.count() == initial_orders + 2
