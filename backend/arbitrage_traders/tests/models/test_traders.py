"""
Тесты моделей ArbitrageTrader.
Фокус на query count validation и корректность ORM операций.
"""

from collections import deque
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.db import IntegrityError, connection
from django.forms import ValidationError
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from arbitrage_traders.domain import ArbitrageTrader as DomainArbitrageTrader
from arbitrage_traders.domain.schemas import ArbitrageCandle as DomainArbitrageCandle
from arbitrage_traders.domain.schemas import (
    ArbitrageTraderError as DomainArbitrageTraderError,
)
from arbitrage_traders.domain.schemas import (
    ArbitrageTraderPosition as DomainArbitrageTraderPosition,
)
from arbitrage_traders.domain.schemas import (
    ArbitrageTraderSignal as DomainArbitrageTraderSignal,
)
from arbitrage_traders.models import (
    ArbitrageExchangeCandle,
    ArbitrageTrader,
    ArbitrageTraderError,
    ArbitrageTraderOrder,
    ArbitrageTraderPosition,
    ArbitrageTraderSignal,
)
from arbitrage_traders.schemas import (
    ArbitragePositionCloseReason,
    ArbitragePositionStatus,
    ArbitragePositionType,
    ArbitrageSignalType,
    ArbitrageTraderStatus,
)
from exchange_clients.domain import ExchangeClientOrder, OrderType
from exchange_clients.domain.exchange_clients import KrakenExchangeClient
from exchange_clients.models import ExchangeClient as ExchangeClientModel
from exchange_clients.models import ExchangeClientOrder as ExchangeClientOrderModel
from exchange_clients.schemas import OrderSide, OrderStatus
from exchanges.domain import ExchangeCandle as DomainExchangeCandle
from exchanges.domain import TradingPair as DomainTradingPair
from exchanges.models import Exchange
from exchanges.models import ExchangeCandle as ExchangeCandleModel
from exchanges.schemas import Timeframe

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
            arbitrage_trader.timeframe == arbitrage_trader.left_candle_source.timeframe
        )

    def test_trading_pair_property(self, arbitrage_trader):
        """Тест свойства trading_pair."""
        assert (
            arbitrage_trader.trading_pair
            == arbitrage_trader.left_candle_source.trading_pair
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
        assert domain_position.left_open_price == arbitrage_position.left_open_price
        assert domain_position.right_open_price == arbitrage_position.right_open_price

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
        right_candle_source,
        exchange_client,
        arbitrage_strategy,
        arbitrage_risk_manager,
    ):
        """Тест что нельзя создать трейдера с одинаковыми клиентами."""

        trader = ArbitrageTrader(
            left_candle_source=candle_source,
            right_candle_source=right_candle_source,
            left_exchange_client=exchange_client,
            right_exchange_client=exchange_client,
            strategy=arbitrage_strategy,
            risk_manager=arbitrage_risk_manager,
            initial_balance=Decimal("1000.00"),
        )

        with pytest.raises(ValidationError):
            trader.clean()

    def test_clean_mismatched_left_candle_source_exchange(
        self,
        candle_source,
        right_candle_source,
        exchange_client,
        right_exchange_client,
        arbitrage_strategy,
        arbitrage_risk_manager,
    ):
        """Тест что биржа первого источника свечей должна совпадать с биржей первого клиента."""

        # left_candle_source привязан к exchange_client (Bybit),
        # но left_exchange_client = right_exchange_client (Binance)
        trader = ArbitrageTrader(
            left_candle_source=candle_source,
            right_candle_source=right_candle_source,
            left_exchange_client=right_exchange_client,
            right_exchange_client=exchange_client,
            strategy=arbitrage_strategy,
            risk_manager=arbitrage_risk_manager,
            initial_balance=Decimal("1000.00"),
        )

        with pytest.raises(ValidationError, match="первого источника свечей"):
            trader.clean()

    def test_clean_mismatched_right_candle_source_exchange(
        self,
        candle_source,
        right_candle_source,
        exchange_client,
        right_exchange_client,
        arbitrage_strategy,
        arbitrage_risk_manager,
        exchange,
        right_exchange,
    ):
        """Тест что биржа второго источника свечей должна совпадать с биржей второго клиента."""
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
            left_candle_source=candle_source,
            right_candle_source=right_candle_source,
            left_exchange_client=exchange_client,
            right_exchange_client=third_exchange_client,
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
                type=ArbitragePositionType.LONG,
                left_type=ArbitragePositionType.LONG,
                right_type=ArbitragePositionType.SHORT,
                status=ArbitragePositionStatus.OPENED,
                amount=Decimal("0.1"),
                left_open_price=Decimal("50000.00") + i * 100,
                right_open_price=Decimal("50100.00") + i * 100,
                opened_at=datetime.now(UTC) + timedelta(hours=i),
                left_total_fee=Decimal("0.05"),
                right_total_fee=Decimal("0.05"),
            )

        domain_trader = arbitrage_trader.instantiate()

        with CaptureQueriesContext(connection) as queries:
            arbitrage_trader.load(domain_trader)

        # 3 запроса: left_candles + right_candles + positions
        assert len(queries) == 3


# ==================== ArbitrageTrader Reboot Tests ====================


@pytest.mark.django_db
class TestArbitrageTraderReboot:
    """Тесты функции reboot арбитражного трейдера."""

    def test_reboot_skips_if_already_rebooting(self, arbitrage_trader):
        """Тест что reboot пропускается если статус уже REBOOTING."""
        arbitrage_trader.status = ArbitrageTraderStatus.REBOOTING
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
        arbitrage_trader.status = ArbitrageTraderStatus.ENABLED
        arbitrage_trader.save()

        with patch.object(
            arbitrage_trader, "get_candle_iterator", return_value=iter([])
        ):
            arbitrage_trader.reboot()

        arbitrage_trader.refresh_from_db()
        assert arbitrage_trader.status == ArbitrageTraderStatus.PAUSED

    def test_reboot_sets_status_to_error_on_exception(self, arbitrage_trader):
        """Тест что reboot устанавливает статус ERROR при ошибке."""
        arbitrage_trader.status = ArbitrageTraderStatus.ENABLED
        arbitrage_trader.save()

        with patch.object(
            arbitrage_trader,
            "get_candle_iterator",
            side_effect=Exception("Test error"),
        ):
            arbitrage_trader.reboot()

        arbitrage_trader.refresh_from_db()
        assert arbitrage_trader.status == ArbitrageTraderStatus.ERROR
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
        arbitrage_trader.status = ArbitrageTraderStatus.ENABLED
        arbitrage_trader.save()

        with patch.object(
            arbitrage_trader, "get_candle_iterator", return_value=iter([])
        ):
            arbitrage_trader.reboot()

        arbitrage_trader.refresh_from_db()
        assert arbitrage_trader.status == ArbitrageTraderStatus.PAUSED

    def test_reboot_from_disabled_status(self, arbitrage_trader):
        """Тест reboot из статуса DISABLED."""
        arbitrage_trader.status = ArbitrageTraderStatus.DISABLED
        arbitrage_trader.save()

        with patch.object(
            arbitrage_trader, "get_candle_iterator", return_value=iter([])
        ):
            arbitrage_trader.reboot()

        arbitrage_trader.refresh_from_db()
        assert arbitrage_trader.status == ArbitrageTraderStatus.PAUSED


# ==================== ArbitrageTrader Sync Tests ====================


@pytest.fixture
def domain_left_candle(exchange_candle):
    """Создает domain ExchangeCandle (первая биржа) для тестов."""
    return DomainExchangeCandle(
        id=exchange_candle.id,
        dt_unix=int(exchange_candle.timestamp.timestamp() * 1000),
        open=exchange_candle.open,
        high=exchange_candle.high,
        low=exchange_candle.low,
        close=exchange_candle.close,
        volume=exchange_candle.volume,
    )


@pytest.fixture
def domain_right_candle(right_exchange_candle):
    """Создает domain ExchangeCandle (вторая биржа) для тестов."""
    return DomainExchangeCandle(
        id=right_exchange_candle.id,
        dt_unix=int(right_exchange_candle.timestamp.timestamp() * 1000),
        open=right_exchange_candle.open,
        high=right_exchange_candle.high,
        low=right_exchange_candle.low,
        close=right_exchange_candle.close,
        volume=right_exchange_candle.volume,
    )


@pytest.fixture
def domain_signal(domain_left_candle, domain_right_candle):
    """Создает domain ArbitrageTraderSignal для тестов."""
    return DomainArbitrageTraderSignal(
        timestamp=datetime.now(UTC),
        left_type=ArbitrageSignalType.BUY,
        right_type=ArbitrageSignalType.SELL,
        left_price=Decimal("50000.00"),
        right_price=Decimal("50100.00"),
        left_candle=domain_left_candle,
        right_candle=domain_right_candle,
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
    left_order = ExchangeClientOrder(
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
    right_order = ExchangeClientOrder(
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
        type=ArbitragePositionType.LONG,
        left_type=ArbitragePositionType.LONG,
        right_type=ArbitragePositionType.SHORT,
        status=ArbitragePositionStatus.OPENED,
        amount=Decimal("0.1"),
        left_open_price=Decimal("50000.00"),
        right_open_price=Decimal("50100.00"),
        opened_at=datetime.now(UTC),
        left_total_fee=Decimal("5.005"),
        right_total_fee=Decimal("5.005"),
        left_orders=[left_order],
        right_orders=[right_order],
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
        self, arbitrage_trader, domain_signal, exchange_candle, right_exchange_candle
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
        assert saved_signal.left_type == ArbitrageSignalType.BUY
        assert saved_signal.right_type == ArbitrageSignalType.SELL
        assert saved_signal.left_price == Decimal("50000.00")
        assert saved_signal.right_price == Decimal("50100.00")

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
        assert saved_position.type == ArbitragePositionType.LONG
        assert saved_position.left_type == ArbitragePositionType.LONG
        assert saved_position.right_type == ArbitragePositionType.SHORT
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

        with patch("arbitrage_traders.models.traders.send_notification.delay"):
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
        arbitrage_trader.status = ArbitrageTraderStatus.ENABLED
        arbitrage_trader.save()

        domain_trader = arbitrage_trader.instantiate()
        domain_trader.errors = [domain_error]

        with patch("arbitrage_traders.models.traders.send_notification.delay"):
            arbitrage_trader.sync_errors(trader=domain_trader)

        arbitrage_trader.refresh_from_db()
        assert arbitrage_trader.status == ArbitrageTraderStatus.ERROR

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
        right_exchange_candle,
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

        with patch("arbitrage_traders.models.traders.send_notification.delay"):
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


# ==================== ArbitrageTrader HandleCandle / CheckPositions Tests ====================


@pytest.mark.django_db
class TestArbitrageTraderHandleCandle:
    """Тесты ArbitrageTrader.handle_candle()."""

    def test_calls_instantiate_load_sync(
        self, arbitrage_trader, exchange_candle, right_exchange_candle
    ):
        """handle_candle вызывает instantiate, load, asyncio.run и sync."""
        with (
            patch.object(
                ArbitrageTrader,
                "instantiate",
                return_value=arbitrage_trader.instantiate(),
            ) as mock_inst,
            patch.object(ArbitrageTrader, "load") as mock_load,
            patch.object(ArbitrageTrader, "sync") as mock_sync,
            patch(
                "arbitrage_traders.models.traders.asyncio.run",
                side_effect=lambda coro: coro.close(),
            ) as mock_run,
        ):
            arbitrage_trader.handle_candle(
                left_candle=exchange_candle, right_candle=right_exchange_candle
            )
            mock_inst.assert_called_once()
            mock_load.assert_called_once()
            mock_run.assert_called_once()
            mock_sync.assert_called_once()


@pytest.mark.django_db
class TestArbitrageTraderCloseAllOpenedPositions:
    """Тесты ArbitrageTrader.close_all_opened_positions()."""

    def test_calls_instantiate_load_sync(self, arbitrage_trader):
        """close_all_opened_positions вызывает instantiate, load, asyncio.run и sync."""
        with (
            patch.object(
                ArbitrageTrader,
                "instantiate",
                return_value=arbitrage_trader.instantiate(),
            ) as mock_inst,
            patch.object(ArbitrageTrader, "load") as mock_load,
            patch.object(ArbitrageTrader, "sync") as mock_sync,
            patch(
                "arbitrage_traders.models.traders.asyncio.run",
                side_effect=lambda coro: coro.close(),
            ) as mock_run,
        ):
            arbitrage_trader.close_all_opened_positions()
            mock_inst.assert_called_once()
            mock_load.assert_called_once()
            mock_run.assert_called_once()
            mock_sync.assert_called_once()


# ==================== ArbitrageTrader GetAbsoluteUrl Tests ====================


@pytest.mark.django_db
class TestArbitrageTraderGetAbsoluteUrl:
    """Тесты ArbitrageTrader.get_absolute_url()."""

    def test_get_absolute_url_contains_pk(self, arbitrage_trader):
        """Тест что get_absolute_url содержит pk трейдера."""
        url = arbitrage_trader.get_absolute_url()
        assert str(arbitrage_trader.pk) in url

    def test_get_absolute_url_matches_reverse(self, arbitrage_trader):
        """Тест что get_absolute_url совпадает с reverse."""

        expected = reverse(
            "arbitrage_trader_detail", kwargs={"pk": arbitrage_trader.pk}
        )
        assert arbitrage_trader.get_absolute_url() == expected


# ==================== ArbitrageTrader Count Methods Tests ====================


@pytest.mark.django_db
class TestArbitrageTraderCountMethods:
    """Тесты методов подсчёта позиций и ордеров."""

    def test_get_total_positions_count_no_positions(self, arbitrage_trader):
        """Возвращает 0 когда нет позиций."""
        assert arbitrage_trader.get_total_positions_count() == 0

    def test_get_total_positions_count_with_positions(
        self, arbitrage_trader, arbitrage_position, closed_arbitrage_position
    ):
        """Возвращает правильное количество включая opened и closed."""
        assert arbitrage_trader.get_total_positions_count() == 2

    def test_get_total_positions_count_with_orders_no_orders(
        self, arbitrage_trader, arbitrage_position
    ):
        """Возвращает 0 когда у позиций нет ордеров."""
        assert arbitrage_trader.get_total_positions_count_with_orders() == 0

    def test_get_total_positions_count_with_orders_has_orders(
        self, arbitrage_trader, closed_arbitrage_position, arbitrage_order
    ):
        """Возвращает количество позиций с ордерами."""
        assert arbitrage_trader.get_total_positions_count_with_orders() == 1

    def test_get_total_orders_count_no_orders(self, arbitrage_trader):
        """Возвращает 0 когда нет ордеров."""
        assert arbitrage_trader.get_total_orders_count() == 0

    def test_get_total_orders_count_with_orders(
        self, arbitrage_trader, closed_arbitrage_position, arbitrage_order
    ):
        """Возвращает правильное количество ордеров."""
        assert arbitrage_trader.get_total_orders_count() == 1

    def test_count_methods_query_count(
        self, arbitrage_trader, closed_arbitrage_position, arbitrage_order
    ):
        """Каждый метод подсчёта выполняет ровно 1 запрос."""
        with CaptureQueriesContext(connection) as q:
            arbitrage_trader.get_total_positions_count()
        assert len(q) == 1

        with CaptureQueriesContext(connection) as q:
            arbitrage_trader.get_total_positions_count_with_orders()
        assert len(q) == 1

        with CaptureQueriesContext(connection) as q:
            arbitrage_trader.get_total_orders_count()
        assert len(q) == 1


# ==================== ArbitrageTrader WinRate Tests ====================


@pytest.mark.django_db
class TestArbitrageTraderWinRate:
    """Тесты ArbitrageTrader.get_win_rate()."""

    def test_win_rate_no_closed_positions(self, arbitrage_trader):
        """Возвращает 0.0 когда нет закрытых позиций."""
        assert arbitrage_trader.get_win_rate() == 0.0

    def test_win_rate_all_winning(self, arbitrage_trader):
        """Возвращает 1.0 когда все позиции прибыльные."""
        now = datetime.now(UTC)
        ArbitrageTraderPosition.objects.create(
            trader=arbitrage_trader,
            type=ArbitragePositionType.LONG,
            left_type=ArbitragePositionType.LONG,
            right_type=ArbitragePositionType.SHORT,
            status=ArbitragePositionStatus.CLOSED,
            amount=Decimal("1.0"),
            left_open_price=Decimal("100"),
            left_close_price=Decimal("110"),
            right_open_price=Decimal("105"),
            right_close_price=Decimal("95"),
            opened_at=now - timedelta(hours=2),
            closed_at=now,
            left_total_fee=Decimal("0.5"),
            right_total_fee=Decimal("0.5"),
        )
        assert arbitrage_trader.get_win_rate() == 1.0

    def test_win_rate_all_losing(self, arbitrage_trader):
        """Возвращает 0.0 когда все позиции убыточные."""
        now = datetime.now(UTC)
        ArbitrageTraderPosition.objects.create(
            trader=arbitrage_trader,
            type=ArbitragePositionType.LONG,
            left_type=ArbitragePositionType.LONG,
            right_type=ArbitragePositionType.SHORT,
            status=ArbitragePositionStatus.CLOSED,
            amount=Decimal("1.0"),
            left_open_price=Decimal("110"),
            left_close_price=Decimal("100"),
            right_open_price=Decimal("95"),
            right_close_price=Decimal("105"),
            opened_at=now - timedelta(hours=2),
            closed_at=now,
            left_total_fee=Decimal("0.5"),
            right_total_fee=Decimal("0.5"),
        )
        assert arbitrage_trader.get_win_rate() == 0.0

    def test_win_rate_mixed(self, arbitrage_trader):
        """Возвращает правильное соотношение для смешанных результатов."""
        now = datetime.now(UTC)
        # Выигрышная
        ArbitrageTraderPosition.objects.create(
            trader=arbitrage_trader,
            type=ArbitragePositionType.LONG,
            left_type=ArbitragePositionType.LONG,
            right_type=ArbitragePositionType.SHORT,
            status=ArbitragePositionStatus.CLOSED,
            amount=Decimal("1.0"),
            left_open_price=Decimal("100"),
            left_close_price=Decimal("120"),
            right_open_price=Decimal("105"),
            right_close_price=Decimal("95"),
            opened_at=now - timedelta(hours=3),
            closed_at=now - timedelta(hours=2),
            left_total_fee=Decimal("0.5"),
            right_total_fee=Decimal("0.5"),
        )
        # Убыточная
        ArbitrageTraderPosition.objects.create(
            trader=arbitrage_trader,
            type=ArbitragePositionType.LONG,
            left_type=ArbitragePositionType.LONG,
            right_type=ArbitragePositionType.SHORT,
            status=ArbitragePositionStatus.CLOSED,
            amount=Decimal("1.0"),
            left_open_price=Decimal("120"),
            left_close_price=Decimal("100"),
            right_open_price=Decimal("95"),
            right_close_price=Decimal("105"),
            opened_at=now - timedelta(hours=2),
            closed_at=now - timedelta(hours=1),
            left_total_fee=Decimal("0.5"),
            right_total_fee=Decimal("0.5"),
        )
        assert arbitrage_trader.get_win_rate() == 0.5

    def test_win_rate_with_start_date_filter(self, arbitrage_trader):
        """Фильтрует позиции закрытые до start_date."""
        now = datetime.now(UTC)
        # Старая позиция (убыток)
        ArbitrageTraderPosition.objects.create(
            trader=arbitrage_trader,
            type=ArbitragePositionType.LONG,
            left_type=ArbitragePositionType.LONG,
            right_type=ArbitragePositionType.SHORT,
            status=ArbitragePositionStatus.CLOSED,
            amount=Decimal("1.0"),
            left_open_price=Decimal("120"),
            left_close_price=Decimal("100"),
            right_open_price=Decimal("95"),
            right_close_price=Decimal("105"),
            opened_at=now - timedelta(days=10),
            closed_at=now - timedelta(days=9),
            left_total_fee=Decimal("0"),
            right_total_fee=Decimal("0"),
        )
        # Недавняя позиция (выигрыш)
        ArbitrageTraderPosition.objects.create(
            trader=arbitrage_trader,
            type=ArbitragePositionType.LONG,
            left_type=ArbitragePositionType.LONG,
            right_type=ArbitragePositionType.SHORT,
            status=ArbitragePositionStatus.CLOSED,
            amount=Decimal("1.0"),
            left_open_price=Decimal("100"),
            left_close_price=Decimal("110"),
            right_open_price=Decimal("105"),
            right_close_price=Decimal("95"),
            opened_at=now - timedelta(hours=2),
            closed_at=now,
            left_total_fee=Decimal("0"),
            right_total_fee=Decimal("0"),
        )
        assert arbitrage_trader.get_win_rate(start_date=now - timedelta(days=1)) == 1.0

    def test_win_rate_with_end_date_filter(self, arbitrage_trader):
        """Фильтрует позиции с closed_at >= end_date (используется __lt)."""
        now = datetime.now(UTC)
        ArbitrageTraderPosition.objects.create(
            trader=arbitrage_trader,
            type=ArbitragePositionType.LONG,
            left_type=ArbitragePositionType.LONG,
            right_type=ArbitragePositionType.SHORT,
            status=ArbitragePositionStatus.CLOSED,
            amount=Decimal("1.0"),
            left_open_price=Decimal("100"),
            left_close_price=Decimal("110"),
            right_open_price=Decimal("105"),
            right_close_price=Decimal("95"),
            opened_at=now - timedelta(hours=2),
            closed_at=now,
            left_total_fee=Decimal("0"),
            right_total_fee=Decimal("0"),
        )
        # Позиция с closed_at=now исключается при end_date=now
        assert arbitrage_trader.get_win_rate(end_date=now) == 0.0

    def test_win_rate_ignores_opened_positions(
        self, arbitrage_trader, arbitrage_position
    ):
        """Открытые позиции не учитываются."""
        assert arbitrage_trader.get_win_rate() == 0.0

    def test_win_rate_short_position_type(self, arbitrage_trader):
        """Проверка формулы для SHORT: (open-close)*amount."""
        now = datetime.now(UTC)
        ArbitrageTraderPosition.objects.create(
            trader=arbitrage_trader,
            type=ArbitragePositionType.SHORT,
            left_type=ArbitragePositionType.SHORT,
            right_type=ArbitragePositionType.LONG,
            status=ArbitragePositionStatus.CLOSED,
            amount=Decimal("1.0"),
            left_open_price=Decimal("110"),
            left_close_price=Decimal("100"),
            right_open_price=Decimal("95"),
            right_close_price=Decimal("105"),
            opened_at=now - timedelta(hours=2),
            closed_at=now,
            left_total_fee=Decimal("0.5"),
            right_total_fee=Decimal("0.5"),
        )
        assert arbitrage_trader.get_win_rate() == 1.0

    def test_win_rate_query_count(self, arbitrage_trader, closed_arbitrage_position):
        """get_win_rate выполняет не более 2 запросов."""
        with CaptureQueriesContext(connection) as q:
            arbitrage_trader.get_win_rate()
        assert len(q) <= 2


# ==================== ArbitrageTrader AvgCandlesPerPosition Tests ====================


@pytest.mark.django_db
class TestArbitrageTraderAvgCandlesPerPosition:
    """Тесты ArbitrageTrader.get_avg_candles_per_position()."""

    def test_no_closed_positions_returns_none(self, arbitrage_trader):
        """Возвращает None когда нет закрытых позиций."""
        assert arbitrage_trader.get_avg_candles_per_position() is None

    def test_single_position(self, arbitrage_trader):
        """Корректно считает для одной позиции на 5 часов (timeframe=1h → 5)."""
        now = datetime.now(UTC)
        ArbitrageTraderPosition.objects.create(
            trader=arbitrage_trader,
            type=ArbitragePositionType.LONG,
            left_type=ArbitragePositionType.LONG,
            right_type=ArbitragePositionType.SHORT,
            status=ArbitragePositionStatus.CLOSED,
            amount=Decimal("0.1"),
            left_open_price=Decimal("100"),
            left_close_price=Decimal("110"),
            right_open_price=Decimal("105"),
            right_close_price=Decimal("95"),
            opened_at=now - timedelta(hours=5),
            closed_at=now,
            left_total_fee=Decimal("0"),
            right_total_fee=Decimal("0"),
        )
        result = arbitrage_trader.get_avg_candles_per_position()
        assert result == pytest.approx(5.0, abs=0.01)

    def test_multiple_positions_average(self, arbitrage_trader):
        """Средние свечи по нескольким позициям: (4h + 6h) / 2 = 5."""
        now = datetime.now(UTC)
        ArbitrageTraderPosition.objects.create(
            trader=arbitrage_trader,
            type=ArbitragePositionType.LONG,
            left_type=ArbitragePositionType.LONG,
            right_type=ArbitragePositionType.SHORT,
            status=ArbitragePositionStatus.CLOSED,
            amount=Decimal("0.1"),
            left_open_price=Decimal("100"),
            left_close_price=Decimal("110"),
            right_open_price=Decimal("105"),
            right_close_price=Decimal("95"),
            opened_at=now - timedelta(hours=14),
            closed_at=now - timedelta(hours=10),
            left_total_fee=Decimal("0"),
            right_total_fee=Decimal("0"),
        )
        ArbitrageTraderPosition.objects.create(
            trader=arbitrage_trader,
            type=ArbitragePositionType.LONG,
            left_type=ArbitragePositionType.LONG,
            right_type=ArbitragePositionType.SHORT,
            status=ArbitragePositionStatus.CLOSED,
            amount=Decimal("0.2"),
            left_open_price=Decimal("100"),
            left_close_price=Decimal("110"),
            right_open_price=Decimal("105"),
            right_close_price=Decimal("95"),
            opened_at=now - timedelta(hours=8),
            closed_at=now - timedelta(hours=2),
            left_total_fee=Decimal("0"),
            right_total_fee=Decimal("0"),
        )
        result = arbitrage_trader.get_avg_candles_per_position()
        assert result == pytest.approx(5.0, abs=0.01)

    def test_with_date_filter(self, arbitrage_trader):
        """Учитывает start_date фильтр."""
        now = datetime.now(UTC)
        # Старая позиция (2 часа)
        ArbitrageTraderPosition.objects.create(
            trader=arbitrage_trader,
            type=ArbitragePositionType.LONG,
            left_type=ArbitragePositionType.LONG,
            right_type=ArbitragePositionType.SHORT,
            status=ArbitragePositionStatus.CLOSED,
            amount=Decimal("0.1"),
            left_open_price=Decimal("100"),
            left_close_price=Decimal("110"),
            right_open_price=Decimal("105"),
            right_close_price=Decimal("95"),
            opened_at=now - timedelta(days=10, hours=2),
            closed_at=now - timedelta(days=10),
            left_total_fee=Decimal("0"),
            right_total_fee=Decimal("0"),
        )
        # Недавняя позиция (3 часа)
        ArbitrageTraderPosition.objects.create(
            trader=arbitrage_trader,
            type=ArbitragePositionType.LONG,
            left_type=ArbitragePositionType.LONG,
            right_type=ArbitragePositionType.SHORT,
            status=ArbitragePositionStatus.CLOSED,
            amount=Decimal("0.2"),
            left_open_price=Decimal("100"),
            left_close_price=Decimal("110"),
            right_open_price=Decimal("105"),
            right_close_price=Decimal("95"),
            opened_at=now - timedelta(hours=4),
            closed_at=now - timedelta(hours=1),
            left_total_fee=Decimal("0"),
            right_total_fee=Decimal("0"),
        )
        result = arbitrage_trader.get_avg_candles_per_position(
            start_date=now - timedelta(days=1)
        )
        assert result == pytest.approx(3.0, abs=0.01)


# ==================== ArbitrageTrader GetBalance Dynamic Tests ====================


@pytest.mark.django_db
class TestArbitrageTraderGetBalanceDynamic:
    """Тесты ArbitrageTrader.get_balance() с use_fixed_balance=False."""

    def test_dynamic_balance_no_positions(self, arbitrage_trader):
        """Динамический баланс равен initial_balance без закрытых позиций."""
        arbitrage_trader.use_fixed_balance = False
        arbitrage_trader.save()
        assert arbitrage_trader.get_balance() == arbitrage_trader.initial_balance

    def test_dynamic_balance_with_orders(
        self, arbitrage_trader, closed_arbitrage_position, arbitrage_order
    ):
        """Динамический баланс = initial_balance + fact_pnl."""
        arbitrage_trader.use_fixed_balance = False
        arbitrage_trader.save()
        balance = arbitrage_trader.get_balance()
        expected = arbitrage_trader.initial_balance + arbitrage_trader.get_fact_pnl()
        assert balance == expected

    def test_dynamic_balance_with_date(
        self, arbitrage_trader, closed_arbitrage_position, arbitrage_order
    ):
        """Параметр date передаётся в get_fact_pnl(end_date=date)."""
        arbitrage_trader.use_fixed_balance = False
        arbitrage_trader.save()
        past = datetime.now(UTC) - timedelta(days=30)
        balance = arbitrage_trader.get_balance(date=past)
        # Позиция закрыта недавно, PnL с end_date в прошлом = 0
        assert balance == arbitrage_trader.initial_balance


# ==================== ArbitrageTrader GetFactPnl Tests ====================


@pytest.mark.django_db
class TestArbitrageTraderGetFactPnl:
    """Тесты ArbitrageTrader.get_fact_pnl()."""

    def test_no_orders_returns_zero(self, arbitrage_trader):
        """Возвращает 0 когда нет ордеров."""
        assert arbitrage_trader.get_fact_pnl() == Decimal("0.00")

    def test_with_orders(
        self, arbitrage_trader, closed_arbitrage_position, arbitrage_order
    ):
        """Рассчитывает PnL: left BUY(sign=-1), right SELL(sign=+1)."""
        pnl = arbitrage_trader.get_fact_pnl()
        # left: BUY -> sign=-1, price=50000, amount=0.1 -> -5000
        # right: SELL -> sign=+1, price=50100, amount=0.1 -> +5010
        # gross = -5000 + 5010 = 10
        # fee = 5.00 + 5.01 = 10.01
        # pnl = 10 - 10.01 = -0.01
        assert pnl == pytest.approx(Decimal("-0.01"), abs=Decimal("0.001"))

    def test_with_start_date_filter(
        self, arbitrage_trader, closed_arbitrage_position, arbitrage_order
    ):
        """Фильтрует по start_date."""
        future = datetime.now(UTC) + timedelta(days=1)
        assert arbitrage_trader.get_fact_pnl(start_date=future) == Decimal("0.00")

    def test_with_end_date_filter(
        self, arbitrage_trader, closed_arbitrage_position, arbitrage_order
    ):
        """Фильтрует по end_date."""
        past = datetime.now(UTC) - timedelta(days=1)
        assert arbitrage_trader.get_fact_pnl(end_date=past) == Decimal("0.00")

    def test_query_count(
        self, arbitrage_trader, closed_arbitrage_position, arbitrage_order
    ):
        """get_fact_pnl выполняет не более 2 запросов."""
        with CaptureQueriesContext(connection) as q:
            arbitrage_trader.get_fact_pnl()
        assert len(q) <= 2


# ==================== ArbitrageTrader GetTheoreticalPnl Tests ====================


@pytest.mark.django_db
class TestArbitrageTraderGetTheoreticalPnl:
    """Тесты ArbitrageTrader.get_theoretical_pnl()."""

    def test_no_positions_returns_zero(self, arbitrage_trader):
        """Возвращает 0 без закрытых позиций."""
        assert arbitrage_trader.get_theoretical_pnl() == Decimal("0.00")

    def test_long_position(self, arbitrage_trader, closed_arbitrage_position):
        """Рассчитывает PnL для LONG left / SHORT right."""
        pnl = arbitrage_trader.get_theoretical_pnl()
        # left: LONG sign=+1, (50500-50000)*0.1 = 50
        # right: SHORT sign=-1, (49800-50100)*0.1 = -30, -1*(-30) = 30
        # gross = 50 + 30 = 80, fee = 0.20
        # pnl = 80 - 0.20 = 79.80
        assert pnl == pytest.approx(Decimal("79.80"), abs=Decimal("0.01"))

    def test_short_position(self, arbitrage_trader):
        """Рассчитывает PnL для SHORT позиции."""
        now = datetime.now(UTC)
        ArbitrageTraderPosition.objects.create(
            trader=arbitrage_trader,
            type=ArbitragePositionType.SHORT,
            left_type=ArbitragePositionType.SHORT,
            right_type=ArbitragePositionType.LONG,
            status=ArbitragePositionStatus.CLOSED,
            amount=Decimal("1.0"),
            left_open_price=Decimal("110"),
            left_close_price=Decimal("100"),
            right_open_price=Decimal("95"),
            right_close_price=Decimal("105"),
            opened_at=now - timedelta(hours=2),
            closed_at=now,
            left_total_fee=Decimal("1.0"),
            right_total_fee=Decimal("1.0"),
        )
        pnl = arbitrage_trader.get_theoretical_pnl()
        # left: SHORT sign=-1, (100-110)*1=-10, -1*(-10)=10
        # right: LONG sign=+1, (105-95)*1=10
        # gross = 10 + 10 = 20, fee=2 -> pnl=18
        assert pnl == Decimal("18")

    def test_with_start_date_filter(self, arbitrage_trader, closed_arbitrage_position):
        """Фильтрует по start_date."""
        future = datetime.now(UTC) + timedelta(days=1)
        assert arbitrage_trader.get_theoretical_pnl(start_date=future) == Decimal(
            "0.00"
        )

    def test_with_end_date_filter(self, arbitrage_trader, closed_arbitrage_position):
        """Фильтрует по end_date."""
        past = datetime.now(UTC) - timedelta(days=1)
        assert arbitrage_trader.get_theoretical_pnl(end_date=past) == Decimal("0.00")

    def test_query_count(self, arbitrage_trader, closed_arbitrage_position):
        """get_theoretical_pnl выполняет 1 агрегатный запрос."""
        with CaptureQueriesContext(connection) as q:
            arbitrage_trader.get_theoretical_pnl()
        assert len(q) == 1


# ==================== ArbitrageTrader Enable/Disable Tests ====================


@pytest.mark.django_db
class TestArbitrageTraderEnableDisable:
    """Тесты ArbitrageTrader.enable() и disable()."""

    def test_enable_sets_status(self, arbitrage_trader):
        """enable() устанавливает ENABLED и сохраняет в БД."""
        arbitrage_trader.status = ArbitrageTraderStatus.DISABLED
        arbitrage_trader.save()
        arbitrage_trader.enable()
        arbitrage_trader.refresh_from_db()
        assert arbitrage_trader.status == ArbitrageTraderStatus.ENABLED

    def test_disable_sets_status(self, arbitrage_trader):
        """disable() устанавливает DISABLED и сохраняет в БД."""
        arbitrage_trader.disable()
        arbitrage_trader.refresh_from_db()
        assert arbitrage_trader.status == ArbitrageTraderStatus.DISABLED

    def test_enable_from_error(self, arbitrage_trader):
        """enable() работает из статуса ERROR."""
        arbitrage_trader.status = ArbitrageTraderStatus.ERROR
        arbitrage_trader.save()
        arbitrage_trader.enable()
        arbitrage_trader.refresh_from_db()
        assert arbitrage_trader.status == ArbitrageTraderStatus.ENABLED

    def test_disable_from_paused(self, arbitrage_trader):
        """disable() работает из статуса PAUSED."""
        arbitrage_trader.status = ArbitrageTraderStatus.PAUSED
        arbitrage_trader.save()
        arbitrage_trader.disable()
        arbitrage_trader.refresh_from_db()
        assert arbitrage_trader.status == ArbitrageTraderStatus.DISABLED

    def test_enable_query_count(self, arbitrage_trader):
        """enable() выполняет ровно 1 UPDATE запрос."""
        arbitrage_trader.status = ArbitrageTraderStatus.DISABLED
        arbitrage_trader.save()
        with CaptureQueriesContext(connection) as q:
            arbitrage_trader.enable()
        assert len(q) == 1


# ==================== ArbitrageTrader HasExistingSignal Tests ====================


@pytest.mark.django_db
class TestArbitrageTraderHasExistingSignal:
    """Тесты ArbitrageTrader.has_existing_signal()."""

    def test_returns_true_when_signal_exists(self, arbitrage_trader, arbitrage_signal):
        """Возвращает True когда сигнал с таким timestamp свечи есть."""
        assert (
            arbitrage_trader.has_existing_signal(
                timestamp=arbitrage_signal.left_candle.timestamp
            )
            is True
        )

    def test_returns_false_when_no_signal(self, arbitrage_trader, exchange_candle):
        """Возвращает False когда нет сигнала."""
        assert (
            arbitrage_trader.has_existing_signal(timestamp=exchange_candle.timestamp)
            is False
        )

    def test_query_count(self, arbitrage_trader, exchange_candle):
        """Выполняет ровно 1 EXISTS запрос."""
        with CaptureQueriesContext(connection) as q:
            arbitrage_trader.has_existing_signal(timestamp=exchange_candle.timestamp)
        assert len(q) == 1


# ==================== ArbitrageTrader ClearAllErrors Tests ====================


@pytest.mark.django_db
class TestArbitrageTraderClearAllErrors:
    """Тесты ArbitrageTrader.clear_all_errors()."""

    def test_clears_all_errors(self, arbitrage_trader):
        """Удаляет все ошибки трейдера."""
        ArbitrageTraderError.objects.create(
            trader=arbitrage_trader, message="Error 1", type="E1"
        )
        ArbitrageTraderError.objects.create(
            trader=arbitrage_trader, message="Error 2", type="E2"
        )
        assert ArbitrageTraderError.objects.filter(trader=arbitrage_trader).count() == 2
        arbitrage_trader.clear_all_errors()
        assert ArbitrageTraderError.objects.filter(trader=arbitrage_trader).count() == 0

    def test_clear_errors_empty(self, arbitrage_trader):
        """Не падает когда ошибок нет."""
        arbitrage_trader.clear_all_errors()
        assert ArbitrageTraderError.objects.filter(trader=arbitrage_trader).count() == 0

    def test_clear_errors_does_not_affect_other_traders(
        self,
        arbitrage_trader,
        candle_source,
        right_candle_source,
        exchange_client,
        right_exchange_client,
        arbitrage_strategy,
        arbitrage_risk_manager,
    ):
        """Удаляет ошибки только целевого трейдера."""
        other_trader = ArbitrageTrader.objects.create(
            left_candle_source=candle_source,
            right_candle_source=right_candle_source,
            left_exchange_client=exchange_client,
            right_exchange_client=right_exchange_client,
            strategy=arbitrage_strategy,
            risk_manager=arbitrage_risk_manager,
            initial_balance=Decimal("500"),
        )
        ArbitrageTraderError.objects.create(
            trader=arbitrage_trader, message="Mine", type="E"
        )
        ArbitrageTraderError.objects.create(
            trader=other_trader, message="Theirs", type="E"
        )
        arbitrage_trader.clear_all_errors()
        assert ArbitrageTraderError.objects.filter(trader=other_trader).count() == 1


# ==================== ArbitrageTrader GetCandleIterator Tests ====================


@pytest.mark.django_db
class TestArbitrageTraderGetCandleIterator:
    """Тесты ArbitrageTrader.get_candle_iterator()."""

    def test_yields_paired_domain_candles(
        self, arbitrage_trader, exchange_candle, right_exchange_candle
    ):
        """Возвращает ArbitrageCandle с domain свечами."""
        right_exchange_candle.timestamp = exchange_candle.timestamp
        right_exchange_candle.save()

        candles = list(arbitrage_trader.get_candle_iterator())
        assert len(candles) == 1
        arb_candle = candles[0]
        assert isinstance(arb_candle, DomainArbitrageCandle)
        assert isinstance(arb_candle.left, DomainExchangeCandle)
        assert isinstance(arb_candle.right, DomainExchangeCandle)

    def test_desync_skips_unmatched_candles(
        self, arbitrage_trader, exchange, right_exchange, trading_pair
    ):
        """Свечи с разными timestamps пропускаются без ошибки."""

        now = datetime.now(UTC)
        ExchangeCandleModel.objects.create(
            exchange=exchange,
            trading_pair=trading_pair,
            timeframe=Timeframe.ONE_HOUR,
            timestamp=now,
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("90"),
            close=Decimal("105"),
            volume=Decimal("100"),
        )
        ExchangeCandleModel.objects.create(
            exchange=right_exchange,
            trading_pair=trading_pair,
            timeframe=Timeframe.ONE_HOUR,
            timestamp=now + timedelta(hours=1),
            open=Decimal("101"),
            high=Decimal("111"),
            low=Decimal("91"),
            close=Decimal("106"),
            volume=Decimal("100"),
        )
        pairs = list(arbitrage_trader.get_candle_iterator())
        assert pairs == []
        arbitrage_trader.refresh_from_db()
        assert arbitrage_trader.status != ArbitrageTraderStatus.ERROR
        assert not ArbitrageTraderError.objects.filter(
            trader=arbitrage_trader,
        ).exists()

    def test_empty_candles(self, arbitrage_trader):
        """Пустой итератор когда нет свечей."""
        pairs = list(arbitrage_trader.get_candle_iterator())
        assert pairs == []

    def test_with_start_filter_excludes_candles(
        self, arbitrage_trader, exchange_candle, right_exchange_candle
    ):
        """Параметр start передаётся обоим источникам свечей."""
        right_exchange_candle.timestamp = exchange_candle.timestamp
        right_exchange_candle.save()
        future = datetime.now(UTC) + timedelta(days=1)
        pairs = list(arbitrage_trader.get_candle_iterator(start=future))
        assert pairs == []


# ==================== ArbitrageTraderSignal Model Tests ====================


@pytest.mark.django_db
class TestArbitrageTraderSignalModel:
    """Тесты модели ArbitrageTraderSignal."""

    def test_str_representation(self, arbitrage_signal):
        """Строковое представление содержит pk трейдера."""
        s = str(arbitrage_signal)
        assert str(arbitrage_signal.trader.pk) in s

    def test_instantiate_returns_domain_signal(self, arbitrage_signal):
        """instantiate() возвращает DomainArbitrageTraderSignal."""
        domain = arbitrage_signal.instantiate()
        assert isinstance(domain, DomainArbitrageTraderSignal)
        assert domain.id == arbitrage_signal.pk
        assert domain.timestamp == arbitrage_signal.timestamp
        assert domain.left_price == arbitrage_signal.left_price
        assert domain.right_price == arbitrage_signal.right_price


# ==================== ArbitrageTraderOrder Model Tests ====================


@pytest.mark.django_db
class TestArbitrageTraderOrderModel:
    """Тесты модели ArbitrageTraderOrder."""

    def test_str_representation(self, arbitrage_order):
        """Строковое представление содержит данные ордеров."""
        s = str(arbitrage_order)
        assert str(arbitrage_order.left_order.amount) in s

    def test_clean_valid_order(self, arbitrage_order):
        """clean() проходит для корректного ордера."""
        arbitrage_order.clean()

    def test_clean_mismatched_trader_raises_error(
        self,
        arbitrage_order,
        candle_source,
        right_candle_source,
        exchange_client,
        right_exchange_client,
        arbitrage_strategy,
        arbitrage_risk_manager,
    ):
        """clean() бросает ValidationError при position.trader != self.trader."""

        other_trader = ArbitrageTrader.objects.create(
            left_candle_source=candle_source,
            right_candle_source=right_candle_source,
            left_exchange_client=exchange_client,
            right_exchange_client=right_exchange_client,
            strategy=arbitrage_strategy,
            risk_manager=arbitrage_risk_manager,
            initial_balance=Decimal("500"),
        )
        arbitrage_order.trader = other_trader
        with pytest.raises(ValidationError, match="тому же арбитражному трейдеру"):
            arbitrage_order.clean()

    def test_instantiate_returns_tuple(self, arbitrage_order):
        """instantiate() возвращает tuple из двух domain ордеров."""
        result = arbitrage_order.instantiate()
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], ExchangeClientOrder)
        assert isinstance(result[1], ExchangeClientOrder)


# ==================== ArbitrageTraderPosition PnlPct Tests ====================


@pytest.mark.django_db
class TestArbitrageTraderPositionPnlPct:
    """Тесты ArbitrageTraderPosition.pnl_pct и __str__."""

    def test_pnl_pct_opened_returns_none(self, arbitrage_position):
        """pnl_pct для открытой позиции возвращает None."""
        assert arbitrage_position.pnl_pct is None

    def test_pnl_pct_closed_returns_percentage(self, closed_arbitrage_position):
        """pnl_pct для закрытой позиции возвращает корректный процент."""
        pnl_pct = closed_arbitrage_position.pnl_pct
        assert pnl_pct is not None
        pnl = closed_arbitrage_position.pnl
        open_cost = closed_arbitrage_position.open_cost
        expected = 100 * pnl / open_cost
        assert pnl_pct == pytest.approx(expected, abs=Decimal("0.01"))

    def test_str_closed_shows_pnl(self, closed_arbitrage_position):
        """__str__ для закрытой позиции содержит числовой PNL."""
        s = str(closed_arbitrage_position)
        assert "PNL:" in s
        assert "N/A" not in s

    def test_str_opened_shows_na(self, arbitrage_position):
        """__str__ для открытой позиции показывает N/A."""
        s = str(arbitrage_position)
        assert "N/A" in s


# ==================== ArbitrageTrader Load Edge Cases ====================


@pytest.mark.django_db
class TestArbitrageTraderLoadEdgeCases:
    """Edge case тесты для ArbitrageTrader.load()."""

    def test_load_empty_no_candles_no_positions(self, arbitrage_trader):
        """load() работает когда у трейдера нет данных."""
        domain_trader = arbitrage_trader.instantiate()
        arbitrage_trader.load(trader=domain_trader)
        assert len(domain_trader.candles) == 0
        assert len(domain_trader.positions) == 0

    def test_load_candles_limited_to_999(self, arbitrage_trader):
        """load() загружает максимум 999 свечей (1000 минус последняя)."""
        now = datetime.now(UTC)
        left_exchange = arbitrage_trader.left_candle_source.exchange_client.exchange
        right_exchange = arbitrage_trader.right_candle_source.exchange_client.exchange
        tp = arbitrage_trader.left_candle_source.trading_pair

        left_candles = [
            ExchangeCandleModel(
                exchange=left_exchange,
                trading_pair=tp,
                timeframe=Timeframe.ONE_HOUR,
                timestamp=now + timedelta(hours=i),
                open=Decimal("50000"),
                high=Decimal("51000"),
                low=Decimal("49000"),
                close=Decimal("50500"),
                volume=Decimal("100"),
            )
            for i in range(1005)
        ]
        ExchangeCandleModel.objects.bulk_create(left_candles)

        right_candles = [
            ExchangeCandleModel(
                exchange=right_exchange,
                trading_pair=tp,
                timeframe=Timeframe.ONE_HOUR,
                timestamp=now + timedelta(hours=i),
                open=Decimal("50100"),
                high=Decimal("51100"),
                low=Decimal("49100"),
                close=Decimal("50600"),
                volume=Decimal("100"),
            )
            for i in range(1005)
        ]
        ExchangeCandleModel.objects.bulk_create(right_candles)

        domain_trader = arbitrage_trader.instantiate()
        arbitrage_trader.load(trader=domain_trader)
        # 1000 загружается, минус последняя (формируется) = 999
        assert len(domain_trader.candles) == 999

    def test_load_candles_chronological_order(self, arbitrage_trader):
        """Свечи загружаются в хронологическом порядке (oldest first)."""
        now = datetime.now(UTC)
        left_exchange = arbitrage_trader.left_candle_source.exchange_client.exchange
        right_exchange = arbitrage_trader.right_candle_source.exchange_client.exchange
        tp = arbitrage_trader.left_candle_source.trading_pair

        for i in range(3):
            ExchangeCandleModel.objects.create(
                exchange=left_exchange,
                trading_pair=tp,
                timeframe=Timeframe.ONE_HOUR,
                timestamp=now + timedelta(hours=i),
                open=Decimal("50000"),
                high=Decimal("51000"),
                low=Decimal("49000"),
                close=Decimal("50500"),
                volume=Decimal("100"),
            )
            ExchangeCandleModel.objects.create(
                exchange=right_exchange,
                trading_pair=tp,
                timeframe=Timeframe.ONE_HOUR,
                timestamp=now + timedelta(hours=i),
                open=Decimal("50100"),
                high=Decimal("51100"),
                low=Decimal("49100"),
                close=Decimal("50600"),
                volume=Decimal("100"),
            )
        domain_trader = arbitrage_trader.instantiate()
        arbitrage_trader.load(trader=domain_trader)
        # 3 свечи минус последняя = 2
        timestamps = [c.timestamp for c in domain_trader.candles]
        assert timestamps == sorted(timestamps)

    def test_load_only_opened_positions(
        self, arbitrage_trader, arbitrage_position, closed_arbitrage_position
    ):
        """load() загружает только OPENED позиции."""
        domain_trader = arbitrage_trader.instantiate()
        arbitrage_trader.load(trader=domain_trader)
        assert len(domain_trader.positions) == 1


# ==================== ArbitrageTrader SyncPositions Upsert Tests ====================


@pytest.mark.django_db
class TestArbitrageTraderSyncPositionsUpsert:
    """Тесты sync_positions с upsert (update_conflicts)."""

    def test_upsert_updates_existing_position(self, arbitrage_trader):
        """При совпадении unique fields обновляет существующую позицию."""
        now = datetime.now(UTC)
        ArbitrageTraderPosition.objects.create(
            trader=arbitrage_trader,
            type=ArbitragePositionType.LONG,
            left_type=ArbitragePositionType.LONG,
            right_type=ArbitragePositionType.SHORT,
            status=ArbitragePositionStatus.OPENED,
            amount=Decimal("0.1"),
            left_open_price=Decimal("50000"),
            right_open_price=Decimal("50100"),
            opened_at=now,
            left_total_fee=Decimal("0.05"),
            right_total_fee=Decimal("0.05"),
        )
        domain_pos = DomainArbitrageTraderPosition(
            type=ArbitragePositionType.LONG,
            left_type=ArbitragePositionType.LONG,
            right_type=ArbitragePositionType.SHORT,
            status=ArbitragePositionStatus.CLOSED,
            amount=Decimal("0.1"),
            left_open_price=Decimal("50000"),
            left_close_price=Decimal("51000"),
            right_open_price=Decimal("50100"),
            right_close_price=Decimal("49500"),
            opened_at=now,
            closed_at=now + timedelta(hours=1),
            close_reason=ArbitragePositionCloseReason.STRATEGY,
            left_total_fee=Decimal("0.10"),
            right_total_fee=Decimal("0.10"),
        )
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.positions = [domain_pos]
        arbitrage_trader.sync_positions(trader=domain_trader)

        assert (
            ArbitrageTraderPosition.objects.filter(trader=arbitrage_trader).count() == 1
        )
        pos = ArbitrageTraderPosition.objects.get(
            trader=arbitrage_trader, opened_at=now
        )
        assert pos.status == ArbitragePositionStatus.CLOSED
        assert pos.left_close_price == Decimal("51000")

    def test_sync_positions_query_count(self, arbitrage_trader, domain_position):
        """sync_positions выполняет 1 запрос (bulk_create с update_conflicts)."""
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.positions = [domain_position]
        with CaptureQueriesContext(connection) as q:
            arbitrage_trader.sync_positions(trader=domain_trader)
        assert len(q) == 1


# ==================== ArbitrageTrader Sync Query Counts ====================


@pytest.mark.django_db
class TestArbitrageTraderSyncQueryCounts:
    """Тесты количества запросов для всех sync методов."""

    def test_sync_signals_query_count(
        self, arbitrage_trader, domain_signal, exchange_candle, right_exchange_candle
    ):
        """sync_signals выполняет 1 bulk_create запрос."""
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.signals = deque([domain_signal])
        with CaptureQueriesContext(connection) as q:
            arbitrage_trader.sync_signals(trader=domain_trader)
        assert len(q) == 1

    def test_sync_orders_query_count(self, arbitrage_trader, domain_position):
        """sync_orders выполняет ограниченное количество запросов."""
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.positions = [domain_position]
        arbitrage_trader.sync_positions(trader=domain_trader)

        with CaptureQueriesContext(connection) as q:
            arbitrage_trader.sync_orders(trader=domain_trader)
        # 2 bulk_create (left + right) + 2 filter + 1 positions + 1 bulk_create orders
        assert len(q) <= 6

    def test_sync_errors_query_count(self, arbitrage_trader, domain_error):
        """sync_errors выполняет 2 запроса: bulk_create + save status."""
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.errors = [domain_error]
        with CaptureQueriesContext(connection) as q:
            arbitrage_trader.sync_errors(trader=domain_trader)
        assert len(q) == 2

    def test_sync_signals_empty_no_queries(self, arbitrage_trader):
        """sync_signals с пустым deque — 0 запросов."""
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.signals = deque()
        with CaptureQueriesContext(connection) as q:
            arbitrage_trader.sync_signals(trader=domain_trader)
        assert len(q) == 0

    def test_sync_positions_empty_no_queries(self, arbitrage_trader):
        """sync_positions с пустым списком — 0 запросов."""
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.positions = []
        with CaptureQueriesContext(connection) as q:
            arbitrage_trader.sync_positions(trader=domain_trader)
        assert len(q) == 0

    def test_sync_errors_empty_no_queries(self, arbitrage_trader):
        """sync_errors с пустым списком — 0 запросов."""
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.errors = []
        with CaptureQueriesContext(connection) as q:
            arbitrage_trader.sync_errors(trader=domain_trader)
        assert len(q) == 0


# ==================== Load Corner Cases ====================


@pytest.mark.django_db
class TestArbitrageTraderLoadCornerCases:
    """Дополнительные corner case тесты для load()."""

    def test_load_candles_instantiate_correctly(self, arbitrage_trader):
        """load() корректно создаёт доменные свечи из ORM."""
        now = datetime.now(UTC)
        left_exchange = arbitrage_trader.left_candle_source.exchange_client.exchange
        right_exchange = arbitrage_trader.right_candle_source.exchange_client.exchange
        tp = arbitrage_trader.left_candle_source.trading_pair

        # Создаём 2 свечи — load() исключит последнюю
        for i in range(2):
            ExchangeCandleModel.objects.create(
                exchange=left_exchange,
                trading_pair=tp,
                timeframe=Timeframe.ONE_HOUR,
                timestamp=now + timedelta(hours=i),
                open=Decimal("50000"),
                high=Decimal("51000"),
                low=Decimal("49000"),
                close=Decimal("50500"),
                volume=Decimal("100"),
            )
            ExchangeCandleModel.objects.create(
                exchange=right_exchange,
                trading_pair=tp,
                timeframe=Timeframe.ONE_HOUR,
                timestamp=now + timedelta(hours=i),
                open=Decimal("50100"),
                high=Decimal("51100"),
                low=Decimal("49100"),
                close=Decimal("50600"),
                volume=Decimal("100"),
            )

        domain_trader = arbitrage_trader.instantiate()
        arbitrage_trader.load(trader=domain_trader)

        assert len(domain_trader.candles) == 1

    def test_load_no_n_plus_one(self, arbitrage_trader):
        """load() загружает свечи и позиции за 3 запроса (без N+1)."""
        now = datetime.now(UTC)
        left_exchange = arbitrage_trader.left_candle_source.exchange_client.exchange
        right_exchange = arbitrage_trader.right_candle_source.exchange_client.exchange
        tp = arbitrage_trader.left_candle_source.trading_pair

        left_candles = [
            ExchangeCandleModel(
                exchange=left_exchange,
                trading_pair=tp,
                timeframe=Timeframe.ONE_HOUR,
                timestamp=now + timedelta(hours=i),
                open=Decimal("50000"),
                high=Decimal("51000"),
                low=Decimal("49000"),
                close=Decimal("50500"),
                volume=Decimal("100"),
            )
            for i in range(10)
        ]
        ExchangeCandleModel.objects.bulk_create(left_candles)

        right_candles = [
            ExchangeCandleModel(
                exchange=right_exchange,
                trading_pair=tp,
                timeframe=Timeframe.ONE_HOUR,
                timestamp=now + timedelta(hours=i),
                open=Decimal("50100"),
                high=Decimal("51100"),
                low=Decimal("49100"),
                close=Decimal("50600"),
                volume=Decimal("100"),
            )
            for i in range(10)
        ]
        ExchangeCandleModel.objects.bulk_create(right_candles)

        domain_trader = arbitrage_trader.instantiate()
        with CaptureQueriesContext(connection) as q:
            arbitrage_trader.load(trader=domain_trader)
        # left_candles + right_candles + positions = 3 запроса
        assert len(q) == 3
        assert len(domain_trader.candles) == 9

    def test_load_positions_ordered_by_opened_at(self, arbitrage_trader):
        """load() загружает позиции отсортированные по opened_at (oldest first)."""
        now = datetime.now(UTC)
        for i in [2, 0, 1]:
            ArbitrageTraderPosition.objects.create(
                trader=arbitrage_trader,
                type=ArbitragePositionType.LONG,
                left_type=ArbitragePositionType.LONG,
                right_type=ArbitragePositionType.SHORT,
                status=ArbitragePositionStatus.OPENED,
                amount=Decimal(str(0.1 + i * 0.01)),
                left_open_price=Decimal("50000"),
                right_open_price=Decimal("50100"),
                opened_at=now + timedelta(hours=i),
                left_total_fee=Decimal("0.05"),
                right_total_fee=Decimal("0.05"),
            )
        domain_trader = arbitrage_trader.instantiate()
        arbitrage_trader.load(trader=domain_trader)

        opened_ats = [p.opened_at for p in domain_trader.positions]
        assert opened_ats == sorted(opened_ats)

    def test_load_positions_with_select_related_no_n_plus_one(self, arbitrage_trader):
        """load() позиций не генерирует N+1 при обращении к trader."""
        now = datetime.now(UTC)
        for i in range(5):
            ArbitrageTraderPosition.objects.create(
                trader=arbitrage_trader,
                type=ArbitragePositionType.LONG,
                left_type=ArbitragePositionType.LONG,
                right_type=ArbitragePositionType.SHORT,
                status=ArbitragePositionStatus.OPENED,
                amount=Decimal(str(0.1 + i * 0.01)),
                left_open_price=Decimal("50000"),
                right_open_price=Decimal("50100"),
                opened_at=now + timedelta(hours=i),
                left_total_fee=Decimal("0.05"),
                right_total_fee=Decimal("0.05"),
            )
        domain_trader = arbitrage_trader.instantiate()
        with CaptureQueriesContext(connection) as q:
            arbitrage_trader.load(trader=domain_trader)
        # left_candles + right_candles + positions = 3 запроса
        assert len(q) == 3
        assert len(domain_trader.positions) == 5


# ==================== Sync Signals Corner Cases ====================


@pytest.mark.django_db
class TestArbitrageTraderSyncSignalsCornerCases:
    """Corner case тесты для sync_signals()."""

    def test_sync_signals_mix_new_and_existing(
        self,
        arbitrage_trader,
        domain_signal,
        arbitrage_signal,
        domain_left_candle,
        domain_right_candle,
    ):
        """sync_signals с mix новых и существующих — создаёт только новые."""
        existing_signal = DomainArbitrageTraderSignal(
            id=arbitrage_signal.id,
            timestamp=arbitrage_signal.timestamp,
            left_type=ArbitrageSignalType.BUY,
            right_type=ArbitrageSignalType.SELL,
            left_price=Decimal("50000"),
            right_price=Decimal("50100"),
            left_candle=domain_left_candle,
            right_candle=domain_right_candle,
            data={},
        )
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.signals = deque([existing_signal, domain_signal])

        initial_count = ArbitrageTraderSignal.objects.filter(
            trader=arbitrage_trader
        ).count()

        arbitrage_trader.sync_signals(trader=domain_trader)

        assert (
            ArbitrageTraderSignal.objects.filter(trader=arbitrage_trader).count()
            == initial_count + 1
        )

    def test_sync_signals_preserves_data_json(
        self, arbitrage_trader, exchange_candle, right_exchange_candle
    ):
        """sync_signals сохраняет JSON data поле."""
        left_candle = DomainExchangeCandle(
            id=exchange_candle.pk,
            dt_unix=int(exchange_candle.timestamp.timestamp() * 1000),
            open=exchange_candle.open,
            high=exchange_candle.high,
            low=exchange_candle.low,
            close=exchange_candle.close,
            volume=exchange_candle.volume,
        )
        right_candle = DomainExchangeCandle(
            id=right_exchange_candle.pk,
            dt_unix=int(right_exchange_candle.timestamp.timestamp() * 1000),
            open=right_exchange_candle.open,
            high=right_exchange_candle.high,
            low=right_exchange_candle.low,
            close=right_exchange_candle.close,
            volume=right_exchange_candle.volume,
        )
        signal_with_data = DomainArbitrageTraderSignal(
            timestamp=datetime.now(UTC),
            left_type=ArbitrageSignalType.BUY,
            right_type=ArbitrageSignalType.SELL,
            left_price=Decimal("50000"),
            right_price=Decimal("50100"),
            left_candle=left_candle,
            right_candle=right_candle,
            data={"spread": 0.5, "price_first": 50000, "price_second": 50100},
        )
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.signals = deque([signal_with_data])
        arbitrage_trader.sync_signals(trader=domain_trader)

        saved = ArbitrageTraderSignal.objects.filter(trader=arbitrage_trader).last()
        assert saved.data == {
            "spread": 0.5,
            "price_first": 50000,
            "price_second": 50100,
        }

    def test_sync_signals_multiple_new(
        self, arbitrage_trader, exchange_candle, right_exchange_candle
    ):
        """sync_signals создаёт несколько сигналов одним bulk_create."""
        now = datetime.now(UTC)
        left_candle = DomainExchangeCandle(
            id=exchange_candle.pk,
            dt_unix=int(exchange_candle.timestamp.timestamp() * 1000),
            open=exchange_candle.open,
            high=exchange_candle.high,
            low=exchange_candle.low,
            close=exchange_candle.close,
            volume=exchange_candle.volume,
        )
        right_candle = DomainExchangeCandle(
            id=right_exchange_candle.pk,
            dt_unix=int(right_exchange_candle.timestamp.timestamp() * 1000),
            open=right_exchange_candle.open,
            high=right_exchange_candle.high,
            low=right_exchange_candle.low,
            close=right_exchange_candle.close,
            volume=right_exchange_candle.volume,
        )
        signals = deque()
        for i in range(5):
            signals.append(
                DomainArbitrageTraderSignal(
                    timestamp=now + timedelta(minutes=i),
                    left_type=ArbitrageSignalType.BUY,
                    right_type=ArbitrageSignalType.SELL,
                    left_price=Decimal("50000") + i,
                    right_price=Decimal("50100") + i,
                    left_candle=left_candle,
                    right_candle=right_candle,
                    data={},
                )
            )
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.signals = signals

        with CaptureQueriesContext(connection) as q:
            arbitrage_trader.sync_signals(trader=domain_trader)
        # Один bulk_create запрос для 5 сигналов
        assert len(q) == 1

        assert (
            ArbitrageTraderSignal.objects.filter(trader=arbitrage_trader).count() == 5
        )


# ==================== Sync Positions Corner Cases ====================


@pytest.mark.django_db
class TestArbitrageTraderSyncPositionsCornerCases:
    """Corner case тесты для sync_positions()."""

    def test_upsert_updates_all_fields(self, arbitrage_trader):
        """Upsert обновляет ВСЕ update_fields при конфликте."""
        now = datetime.now(UTC)
        ArbitrageTraderPosition.objects.create(
            trader=arbitrage_trader,
            type=ArbitragePositionType.LONG,
            left_type=ArbitragePositionType.LONG,
            right_type=ArbitragePositionType.SHORT,
            status=ArbitragePositionStatus.OPENED,
            amount=Decimal("0.1"),
            left_open_price=Decimal("50000"),
            right_open_price=Decimal("50100"),
            opened_at=now,
            left_total_fee=Decimal("0.05"),
            right_total_fee=Decimal("0.05"),
        )
        domain_pos = DomainArbitrageTraderPosition(
            type=ArbitragePositionType.LONG,
            left_type=ArbitragePositionType.LONG,
            right_type=ArbitragePositionType.SHORT,
            status=ArbitragePositionStatus.CLOSED,
            amount=Decimal("0.1"),
            left_open_price=Decimal("50000"),
            left_close_price=Decimal("51000"),
            right_open_price=Decimal("50100"),
            right_close_price=Decimal("49500"),
            opened_at=now,
            closed_at=now + timedelta(hours=2),
            close_reason=ArbitragePositionCloseReason.STRATEGY,
            left_total_fee=Decimal("0.125"),
            right_total_fee=Decimal("0.125"),
        )
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.positions = [domain_pos]
        arbitrage_trader.sync_positions(trader=domain_trader)

        pos = ArbitrageTraderPosition.objects.get(
            trader=arbitrage_trader, opened_at=now
        )
        assert pos.status == ArbitragePositionStatus.CLOSED
        assert pos.left_close_price == Decimal("51000")
        assert pos.right_close_price == Decimal("49500")
        assert pos.closed_at == now + timedelta(hours=2)
        assert pos.close_reason == ArbitragePositionCloseReason.STRATEGY
        assert pos.left_total_fee == Decimal("0.125")
        assert pos.right_total_fee == Decimal("0.125")
        assert pos.left_type == ArbitragePositionType.LONG
        assert pos.right_type == ArbitragePositionType.SHORT
        assert pos.left_open_price == Decimal("50000")
        assert pos.right_open_price == Decimal("50100")

    def test_close_reason_none_saves_empty_string(self, arbitrage_trader):
        """close_reason=None → сохраняется как пустая строка."""
        domain_pos = DomainArbitrageTraderPosition(
            type=ArbitragePositionType.LONG,
            left_type=ArbitragePositionType.LONG,
            right_type=ArbitragePositionType.SHORT,
            status=ArbitragePositionStatus.OPENED,
            amount=Decimal("0.1"),
            left_open_price=Decimal("50000"),
            right_open_price=Decimal("50100"),
            opened_at=datetime.now(UTC),
            left_total_fee=Decimal("0.05"),
            right_total_fee=Decimal("0.05"),
            close_reason=None,
        )
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.positions = [domain_pos]
        arbitrage_trader.sync_positions(trader=domain_trader)

        pos = ArbitrageTraderPosition.objects.filter(trader=arbitrage_trader).last()
        assert pos.close_reason == ""

    def test_upsert_mix_new_and_existing(self, arbitrage_trader):
        """Upsert: часть новых позиций, часть обновляемых."""
        now = datetime.now(UTC)
        ArbitrageTraderPosition.objects.create(
            trader=arbitrage_trader,
            type=ArbitragePositionType.LONG,
            left_type=ArbitragePositionType.LONG,
            right_type=ArbitragePositionType.SHORT,
            status=ArbitragePositionStatus.OPENED,
            amount=Decimal("0.1"),
            left_open_price=Decimal("50000"),
            right_open_price=Decimal("50100"),
            opened_at=now,
            left_total_fee=Decimal("0.05"),
            right_total_fee=Decimal("0.05"),
        )
        existing_updated = DomainArbitrageTraderPosition(
            type=ArbitragePositionType.LONG,
            left_type=ArbitragePositionType.LONG,
            right_type=ArbitragePositionType.SHORT,
            status=ArbitragePositionStatus.CLOSED,
            amount=Decimal("0.1"),
            left_open_price=Decimal("50000"),
            right_open_price=Decimal("50100"),
            opened_at=now,
            closed_at=now + timedelta(hours=1),
            close_reason=ArbitragePositionCloseReason.STRATEGY,
            left_total_fee=Decimal("0.10"),
            right_total_fee=Decimal("0.10"),
        )
        brand_new = DomainArbitrageTraderPosition(
            type=ArbitragePositionType.SHORT,
            left_type=ArbitragePositionType.SHORT,
            right_type=ArbitragePositionType.LONG,
            status=ArbitragePositionStatus.OPENED,
            amount=Decimal("0.2"),
            left_open_price=Decimal("51000"),
            right_open_price=Decimal("50900"),
            opened_at=now + timedelta(hours=2),
            left_total_fee=Decimal("0.075"),
            right_total_fee=Decimal("0.075"),
        )
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.positions = [existing_updated, brand_new]
        arbitrage_trader.sync_positions(trader=domain_trader)

        assert (
            ArbitrageTraderPosition.objects.filter(trader=arbitrage_trader).count() == 2
        )
        updated = ArbitrageTraderPosition.objects.get(
            trader=arbitrage_trader, opened_at=now
        )
        assert updated.status == ArbitragePositionStatus.CLOSED
        new = ArbitrageTraderPosition.objects.get(
            trader=arbitrage_trader, type=ArbitragePositionType.SHORT
        )
        assert new.amount == Decimal("0.2")

    def test_sync_multiple_positions_query_count(self, arbitrage_trader):
        """sync_positions с N позициями = 1 запрос (bulk_create)."""
        now = datetime.now(UTC)
        positions = []
        for i in range(5):
            positions.append(
                DomainArbitrageTraderPosition(
                    type=ArbitragePositionType.LONG,
                    left_type=ArbitragePositionType.LONG,
                    right_type=ArbitragePositionType.SHORT,
                    status=ArbitragePositionStatus.OPENED,
                    amount=Decimal(str(0.1 + i * 0.01)),
                    left_open_price=Decimal("50000"),
                    right_open_price=Decimal("50100"),
                    opened_at=now + timedelta(hours=i),
                    left_total_fee=Decimal("0.05"),
                    right_total_fee=Decimal("0.05"),
                )
            )
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.positions = positions
        with CaptureQueriesContext(connection) as q:
            arbitrage_trader.sync_positions(trader=domain_trader)
        assert len(q) == 1


# ==================== Sync Orders Corner Cases ====================


@pytest.mark.django_db
class TestArbitrageTraderSyncOrdersCornerCases:
    """Corner case тесты для sync_orders()."""

    def test_sync_orders_creates_arbitrage_trader_order(
        self, arbitrage_trader, domain_position
    ):
        """sync_orders создаёт ArbitrageTraderOrder (не только ExchangeClientOrder)."""
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.positions = [domain_position]
        arbitrage_trader.sync_positions(trader=domain_trader)

        arbitrage_trader.sync_orders(trader=domain_trader)

        assert ArbitrageTraderOrder.objects.filter(trader=arbitrage_trader).count() == 1

    def test_sync_orders_links_to_correct_position(
        self, arbitrage_trader, domain_position
    ):
        """sync_orders привязывает ордер к правильной позиции."""
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.positions = [domain_position]
        arbitrage_trader.sync_positions(trader=domain_trader)
        arbitrage_trader.sync_orders(trader=domain_trader)

        order = ArbitrageTraderOrder.objects.get(trader=arbitrage_trader)
        pos = ArbitrageTraderPosition.objects.get(
            trader=arbitrage_trader,
            opened_at=domain_position.opened_at,
        )
        assert order.position == pos

    def test_sync_orders_left_right_exchange_client_orders(
        self, arbitrage_trader, domain_position
    ):
        """sync_orders создаёт left и right ExchangeClientOrder с правильными данными."""
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.positions = [domain_position]
        arbitrage_trader.sync_positions(trader=domain_trader)
        arbitrage_trader.sync_orders(trader=domain_trader)

        order = ArbitrageTraderOrder.objects.get(trader=arbitrage_trader)
        assert order.left_order.exchange_client == arbitrage_trader.left_exchange_client
        assert (
            order.right_order.exchange_client == arbitrage_trader.right_exchange_client
        )
        assert order.left_order.side == OrderSide.BUY
        assert order.right_order.side == OrderSide.SELL

    def test_sync_orders_duplicate_raises_integrity_error(
        self, arbitrage_trader, domain_position
    ):
        """Повторный sync_orders бросает IntegrityError (ExchangeClientOrder unique)."""

        domain_trader = arbitrage_trader.instantiate()
        domain_trader.positions = [domain_position]
        arbitrage_trader.sync_positions(trader=domain_trader)

        arbitrage_trader.sync_orders(trader=domain_trader)
        # Повторный вызов — ExchangeClientOrder.bulk_create без ignore_conflicts
        with pytest.raises(IntegrityError):
            arbitrage_trader.sync_orders(trader=domain_trader)

    def test_sync_orders_position_not_found_skips(
        self, arbitrage_trader, domain_trading_pair
    ):
        """Если позиция не найдена в БД → ордер не создаётся."""
        left_order = ExchangeClientOrder(
            exchange_order_id="orphan-left-001",
            status=OrderStatus.CLOSED,
            type=OrderType.MARKET,
            trading_pair=domain_trading_pair,
            side=OrderSide.BUY,
            timestamp=datetime.now(UTC),
            amount=Decimal("0.1"),
            price=Decimal("50000"),
            cost=Decimal("5000"),
            fee=Decimal("5.00"),
        )
        right_order = ExchangeClientOrder(
            exchange_order_id="orphan-right-001",
            status=OrderStatus.CLOSED,
            type=OrderType.MARKET,
            trading_pair=domain_trading_pair,
            side=OrderSide.SELL,
            timestamp=datetime.now(UTC),
            amount=Decimal("0.1"),
            price=Decimal("50100"),
            cost=Decimal("5010"),
            fee=Decimal("5.01"),
        )
        domain_pos = DomainArbitrageTraderPosition(
            type=ArbitragePositionType.LONG,
            left_type=ArbitragePositionType.LONG,
            right_type=ArbitragePositionType.SHORT,
            status=ArbitragePositionStatus.OPENED,
            amount=Decimal("0.1"),
            left_open_price=Decimal("50000"),
            right_open_price=Decimal("50100"),
            opened_at=datetime.now(UTC),
            left_total_fee=Decimal("5.005"),
            right_total_fee=Decimal("5.005"),
            left_orders=[left_order],
            right_orders=[right_order],
        )
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.positions = [domain_pos]
        # НЕ вызываем sync_positions — позиции нет в БД
        arbitrage_trader.sync_orders(trader=domain_trader)

        assert ArbitrageTraderOrder.objects.filter(trader=arbitrage_trader).count() == 0


# ==================== Sync Errors Corner Cases ====================


@pytest.mark.django_db
class TestArbitrageTraderSyncErrorsCornerCases:
    """Corner case тесты для sync_errors()."""

    def test_sync_errors_sends_notification(self, arbitrage_trader, domain_error):
        """sync_errors вызывает send_notification.delay с правильным сообщением."""
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.errors = [domain_error]

        with patch(
            "arbitrage_traders.models.traders.send_notification.delay"
        ) as mock_notify:
            arbitrage_trader.sync_errors(trader=domain_trader)
            mock_notify.assert_called_once()
            call_msg = mock_notify.call_args[1]["message"]
            assert str(arbitrage_trader.pk) in call_msg
            assert "Test error message" in call_msg

    def test_sync_errors_multiple_in_batch(self, arbitrage_trader):
        """sync_errors с несколькими ошибками — все создаются одним bulk_create."""
        errors = []
        for i in range(3):
            errors.append(
                DomainArbitrageTraderError(
                    timestamp=datetime.now(UTC) + timedelta(seconds=i),
                    message=f"Error {i}",
                    type=f"Error{i}",
                    traceback=f"Traceback {i}",
                )
            )
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.errors = errors

        with patch("arbitrage_traders.models.traders.send_notification.delay"):
            with CaptureQueriesContext(connection) as q:
                arbitrage_trader.sync_errors(trader=domain_trader)
            # 1 bulk_create + 1 save(status)
            assert len(q) == 2

        assert ArbitrageTraderError.objects.filter(trader=arbitrage_trader).count() == 3

    def test_sync_errors_mix_new_and_existing(self, arbitrage_trader):
        """sync_errors с mix новых и существующих — создаёт только новые."""
        existing = ArbitrageTraderError.objects.create(
            trader=arbitrage_trader,
            message="Old error",
            type="OldError",
        )
        existing_domain = DomainArbitrageTraderError(
            id=existing.pk,
            timestamp=datetime.now(UTC),
            message="Old error",
            type="OldError",
            traceback="",
        )
        new_domain = DomainArbitrageTraderError(
            timestamp=datetime.now(UTC),
            message="New error",
            type="NewError",
            traceback="",
        )
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.errors = [existing_domain, new_domain]

        with patch("arbitrage_traders.models.traders.send_notification.delay"):
            arbitrage_trader.sync_errors(trader=domain_trader)

        assert ArbitrageTraderError.objects.filter(trader=arbitrage_trader).count() == 2

    def test_sync_errors_notification_contains_all_messages(self, arbitrage_trader):
        """Уведомление содержит сообщения всех ошибок."""
        errors = [
            DomainArbitrageTraderError(
                timestamp=datetime.now(UTC),
                message="First failure",
                type="Type1",
                traceback="",
            ),
            DomainArbitrageTraderError(
                timestamp=datetime.now(UTC),
                message="Second failure",
                type="Type2",
                traceback="",
            ),
        ]
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.errors = errors

        with patch(
            "arbitrage_traders.models.traders.send_notification.delay"
        ) as mock_notify:
            arbitrage_trader.sync_errors(trader=domain_trader)
            call_msg = mock_notify.call_args[1]["message"]
            assert "First failure" in call_msg
            assert "Second failure" in call_msg


# ==================== Sync Full Cycle Corner Cases ====================


@pytest.mark.django_db
class TestArbitrageTraderSyncFullCycleCornerCases:
    """Corner case тесты для полного цикла sync и round-trip load→sync→load."""

    def test_sync_full_query_count(
        self,
        arbitrage_trader,
        domain_signal,
        domain_position,
        domain_error,
        exchange_candle,
        right_exchange_candle,
    ):
        """sync() полный цикл — ограниченное количество запросов."""
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.signals = deque([domain_signal])
        domain_trader.positions = [domain_position]
        domain_trader.errors = [domain_error]

        with (
            patch("arbitrage_traders.models.traders.send_notification.delay"),
            CaptureQueriesContext(connection) as q,
        ):
            arbitrage_trader.sync(trader=domain_trader)
        # sync_signals: 1, sync_positions: 1, sync_orders: ≤6, sync_errors: 2
        assert len(q) <= 10

    def test_load_candles_round_trip(self, arbitrage_trader):
        """Round-trip: создаём свечи → load → свечи в domain."""
        now = datetime.now(UTC)
        left_exchange = arbitrage_trader.left_candle_source.exchange_client.exchange
        right_exchange = arbitrage_trader.right_candle_source.exchange_client.exchange
        tp = arbitrage_trader.left_candle_source.trading_pair

        # Первый load — пусто
        domain_trader = arbitrage_trader.instantiate()
        arbitrage_trader.load(trader=domain_trader)
        assert len(domain_trader.candles) == 0

        # Создаём 3 свечи, load загрузит 2 (без последней)
        for i in range(3):
            ExchangeCandleModel.objects.create(
                exchange=left_exchange,
                trading_pair=tp,
                timeframe=Timeframe.ONE_HOUR,
                timestamp=now + timedelta(hours=i),
                open=Decimal("50000"),
                high=Decimal("51000"),
                low=Decimal("49000"),
                close=Decimal("50500"),
                volume=Decimal("100"),
            )
            ExchangeCandleModel.objects.create(
                exchange=right_exchange,
                trading_pair=tp,
                timeframe=Timeframe.ONE_HOUR,
                timestamp=now + timedelta(hours=i),
                open=Decimal("50100"),
                high=Decimal("51100"),
                low=Decimal("49100"),
                close=Decimal("50600"),
                volume=Decimal("100"),
            )

        # Второй load — свечи есть (кроме последней)
        domain_trader2 = arbitrage_trader.instantiate()
        arbitrage_trader.load(trader=domain_trader2)
        assert len(domain_trader2.candles) == 2

    def test_load_sync_round_trip_positions(self, arbitrage_trader):
        """Round-trip: load → add position → sync → load → позиция в domain."""
        domain_trader = arbitrage_trader.instantiate()
        arbitrage_trader.load(trader=domain_trader)
        assert len(domain_trader.positions) == 0

        now = datetime.now(UTC)
        domain_trader.positions.append(
            DomainArbitrageTraderPosition(
                type=ArbitragePositionType.LONG,
                left_type=ArbitragePositionType.LONG,
                right_type=ArbitragePositionType.SHORT,
                status=ArbitragePositionStatus.OPENED,
                amount=Decimal("0.1"),
                left_open_price=Decimal("50000"),
                right_open_price=Decimal("50100"),
                opened_at=now,
                left_total_fee=Decimal("0.05"),
                right_total_fee=Decimal("0.05"),
            )
        )
        arbitrage_trader.sync_positions(trader=domain_trader)

        domain_trader2 = arbitrage_trader.instantiate()
        arbitrage_trader.load(trader=domain_trader2)
        assert len(domain_trader2.positions) == 1
        assert domain_trader2.positions[0].left_open_price == Decimal("50000")

    def test_load_sync_round_trip_position_close(self, arbitrage_trader):
        """Round-trip: open → sync → close → sync → load → закрытая не загружается."""
        now = datetime.now(UTC)
        # Сначала создаём открытую позицию
        domain_trader = arbitrage_trader.instantiate()
        domain_trader.positions = [
            DomainArbitrageTraderPosition(
                type=ArbitragePositionType.LONG,
                left_type=ArbitragePositionType.LONG,
                right_type=ArbitragePositionType.SHORT,
                status=ArbitragePositionStatus.OPENED,
                amount=Decimal("0.1"),
                left_open_price=Decimal("50000"),
                right_open_price=Decimal("50100"),
                opened_at=now,
                left_total_fee=Decimal("0.05"),
                right_total_fee=Decimal("0.05"),
            )
        ]
        arbitrage_trader.sync_positions(trader=domain_trader)

        # Загружаем — должна быть 1 позиция
        domain_trader2 = arbitrage_trader.instantiate()
        arbitrage_trader.load(trader=domain_trader2)
        assert len(domain_trader2.positions) == 1

        # Закрываем позицию
        domain_trader2.positions[0].status = ArbitragePositionStatus.CLOSED
        domain_trader2.positions[0].closed_at = now + timedelta(hours=1)
        domain_trader2.positions[0].close_reason = ArbitragePositionCloseReason.STRATEGY
        domain_trader2.positions[0].left_close_price = Decimal("51000")
        domain_trader2.positions[0].right_close_price = Decimal("49500")
        arbitrage_trader.sync_positions(trader=domain_trader2)

        # Загружаем снова — закрытая позиция НЕ загружается в load
        domain_trader3 = arbitrage_trader.instantiate()
        arbitrage_trader.load(trader=domain_trader3)
        assert len(domain_trader3.positions) == 0

        # Но в БД она есть и закрыта
        pos = ArbitrageTraderPosition.objects.get(trader=arbitrage_trader)
        assert pos.status == ArbitragePositionStatus.CLOSED
        assert pos.left_close_price == Decimal("51000")


# ==================== get_last_candles Tests ====================


@pytest.mark.django_db
class TestArbitrageTraderGetLastCandles:
    """Тесты get_last_candles — возвращает list[ArbitrageExchangeCandle]."""

    def test_get_last_candles_returns_list(self, arbitrage_trader):
        """get_last_candles возвращает list."""
        result = arbitrage_trader.get_last_candles(count=2)
        assert isinstance(result, list)

    def test_get_last_candles_delegates_to_candle_sources(self, arbitrage_trader):
        """get_last_candles делегирует обоим candle_source."""
        with (
            patch.object(
                arbitrage_trader.left_candle_source,
                "get_last_candles",
                return_value=[],
            ) as left_mock,
            patch.object(
                arbitrage_trader.right_candle_source,
                "get_last_candles",
                return_value=[],
            ) as right_mock,
        ):
            arbitrage_trader.get_last_candles(count=5)
            left_mock.assert_called_once_with(5)
            right_mock.assert_called_once_with(5)

    def test_get_last_candles_returns_candles(
        self,
        arbitrage_trader,
        exchange,
        right_exchange,
        trading_pair,
    ):
        """get_last_candles возвращает ArbitrageExchangeCandle из обоих источников."""
        now = datetime.now(UTC)
        for i in range(3):
            ExchangeCandleModel.objects.create(
                exchange=exchange,
                trading_pair=trading_pair,
                timeframe=Timeframe.ONE_HOUR,
                timestamp=now - timedelta(hours=i),
                open=Decimal("50000"),
                high=Decimal("51000"),
                low=Decimal("49000"),
                close=Decimal("50500"),
                volume=Decimal("100"),
            )
            ExchangeCandleModel.objects.create(
                exchange=right_exchange,
                trading_pair=trading_pair,
                timeframe=Timeframe.ONE_HOUR,
                timestamp=now - timedelta(hours=i),
                open=Decimal("50100"),
                high=Decimal("51100"),
                low=Decimal("49100"),
                close=Decimal("50600"),
                volume=Decimal("100"),
            )

        candles = arbitrage_trader.get_last_candles(count=2)
        assert len(candles) == 2
        assert isinstance(candles[0], ArbitrageExchangeCandle)
        assert candles[0].left is not None
        assert candles[0].right is not None

    def test_get_last_candles_empty(self, arbitrage_trader):
        """get_last_candles при отсутствии свечей."""
        candles = arbitrage_trader.get_last_candles(count=10)
        assert len(candles) == 0


# ==================== get_pnl_r2 Tests ====================


@pytest.mark.django_db
class TestArbitrageTraderGetPnlR2:
    """Тесты get_pnl_r2 — R² coefficient для cumulative PnL."""

    def test_pnl_r2_no_positions(self, arbitrage_trader):
        """get_pnl_r2 без позиций возвращает 0.0."""
        assert arbitrage_trader.get_pnl_r2() == 0.0

    def test_pnl_r2_single_position(self, arbitrage_trader, closed_arbitrage_position):
        """get_pnl_r2 с 1 позицией возвращает 0.0 (нужно >= 2)."""
        assert arbitrage_trader.get_pnl_r2() == 0.0

    def test_pnl_r2_linear_growth(self, arbitrage_trader):
        """get_pnl_r2 с линейным ростом PnL → R² ≈ 1.0."""
        now = datetime.now(UTC)
        # Создаём 5 закрытых позиций с одинаковым PnL
        for i in range(5):
            ArbitrageTraderPosition.objects.create(
                trader=arbitrage_trader,
                type=ArbitragePositionType.LONG,
                left_type=ArbitragePositionType.LONG,
                right_type=ArbitragePositionType.SHORT,
                status=ArbitragePositionStatus.CLOSED,
                amount=Decimal("1.0"),
                left_open_price=Decimal("50000"),
                left_close_price=Decimal("50100"),
                right_open_price=Decimal("50100"),
                right_close_price=Decimal("50000"),
                opened_at=now - timedelta(hours=10 - i),
                closed_at=now - timedelta(hours=9 - i),
                left_total_fee=Decimal("0.00"),
                right_total_fee=Decimal("0.00"),
                close_reason=ArbitragePositionCloseReason.STRATEGY,
            )
        r2 = arbitrage_trader.get_pnl_r2()
        # Одинаковый PnL = линейный cumulative → R² ≈ 1.0
        assert r2 > 0.95

    def test_pnl_r2_constant_pnl_zero_ss_tot(self, arbitrage_trader):
        """get_pnl_r2 при нулевом ss_tot → 0.0."""
        now = datetime.now(UTC)
        # 2 позиции с одинаковым PnL и одинаковым временем закрытия
        # → cumulative PnL = [pnl, 2*pnl], x = [t, t] → полифит не определён
        # Но если timestamps различаются и PnL одинаков → ss_tot > 0
        # Для ss_tot = 0 нужны одинаковые cumulative, что невозможно
        # Используем две позиции с pnl=0
        for i in range(2):
            ArbitrageTraderPosition.objects.create(
                trader=arbitrage_trader,
                type=ArbitragePositionType.LONG,
                left_type=ArbitragePositionType.LONG,
                right_type=ArbitragePositionType.SHORT,
                status=ArbitragePositionStatus.CLOSED,
                amount=Decimal("1.0"),
                left_open_price=Decimal("50000"),
                left_close_price=Decimal("50000"),
                right_open_price=Decimal("50000"),
                right_close_price=Decimal("50000"),
                opened_at=now - timedelta(hours=3 - i),
                closed_at=now - timedelta(hours=2 - i),
                left_total_fee=Decimal("0.00"),
                right_total_fee=Decimal("0.00"),
                close_reason=ArbitragePositionCloseReason.STRATEGY,
            )
        # cumulative_pnl = [0, 0] → ss_tot = 0 → r2 = 0.0
        r2 = arbitrage_trader.get_pnl_r2()
        assert r2 == 0.0

    def test_pnl_r2_with_start_date(self, arbitrage_trader):
        """get_pnl_r2 с start_date фильтрует позиции."""
        now = datetime.now(UTC)
        # Создаём 4 позиции: 2 старые + 2 новые
        for i in range(4):
            ArbitrageTraderPosition.objects.create(
                trader=arbitrage_trader,
                type=ArbitragePositionType.LONG,
                left_type=ArbitragePositionType.LONG,
                right_type=ArbitragePositionType.SHORT,
                status=ArbitragePositionStatus.CLOSED,
                amount=Decimal("1.0"),
                left_open_price=Decimal("50000"),
                left_close_price=Decimal("50100"),
                right_open_price=Decimal("50100"),
                right_close_price=Decimal("50000"),
                opened_at=now - timedelta(days=10 - i),
                closed_at=now - timedelta(days=9 - i),
                left_total_fee=Decimal("0.00"),
                right_total_fee=Decimal("0.00"),
                close_reason=ArbitragePositionCloseReason.STRATEGY,
            )
        # Фильтр: только 2 последних
        start_date = now - timedelta(days=8)
        r2 = arbitrage_trader.get_pnl_r2(start_date=start_date)
        assert r2 > 0.95

    def test_pnl_r2_with_end_date(self, arbitrage_trader):
        """get_pnl_r2 с end_date фильтрует позиции."""
        now = datetime.now(UTC)
        for i in range(4):
            ArbitrageTraderPosition.objects.create(
                trader=arbitrage_trader,
                type=ArbitragePositionType.LONG,
                left_type=ArbitragePositionType.LONG,
                right_type=ArbitragePositionType.SHORT,
                status=ArbitragePositionStatus.CLOSED,
                amount=Decimal("1.0"),
                left_open_price=Decimal("50000"),
                left_close_price=Decimal("50100"),
                right_open_price=Decimal("50100"),
                right_close_price=Decimal("50000"),
                opened_at=now - timedelta(days=10 - i),
                closed_at=now - timedelta(days=9 - i),
                left_total_fee=Decimal("0.00"),
                right_total_fee=Decimal("0.00"),
                close_reason=ArbitragePositionCloseReason.STRATEGY,
            )
        # Фильтр: только 2 первых
        end_date = now - timedelta(days=7)
        r2 = arbitrage_trader.get_pnl_r2(end_date=end_date)
        assert r2 > 0.95

    def test_pnl_r2_query_count(self, arbitrage_trader):
        """get_pnl_r2 выполняет 1 запрос."""
        now = datetime.now(UTC)
        for i in range(3):
            ArbitrageTraderPosition.objects.create(
                trader=arbitrage_trader,
                type=ArbitragePositionType.LONG,
                left_type=ArbitragePositionType.LONG,
                right_type=ArbitragePositionType.SHORT,
                status=ArbitragePositionStatus.CLOSED,
                amount=Decimal("1.0"),
                left_open_price=Decimal("50000"),
                left_close_price=Decimal("50100"),
                right_open_price=Decimal("50100"),
                right_close_price=Decimal("50000"),
                opened_at=now - timedelta(hours=5 - i),
                closed_at=now - timedelta(hours=4 - i),
                left_total_fee=Decimal("0.00"),
                right_total_fee=Decimal("0.00"),
                close_reason=ArbitragePositionCloseReason.STRATEGY,
            )
        with CaptureQueriesContext(connection) as ctx:
            arbitrage_trader.get_pnl_r2()
        assert len(ctx) == 1

    def test_pnl_r2_mixed_pnl(self, arbitrage_trader):
        """get_pnl_r2 со смешанным PnL → 0 < R² < 1."""
        now = datetime.now(UTC)
        pnl_values = [
            (Decimal("50100"), Decimal("50000")),  # profit
            (Decimal("49800"), Decimal("50200")),  # loss
            (Decimal("50200"), Decimal("49900")),  # profit
            (Decimal("49900"), Decimal("50100")),  # loss
            (Decimal("50300"), Decimal("49800")),  # profit
        ]
        for i, (left_close, right_close) in enumerate(pnl_values):
            ArbitrageTraderPosition.objects.create(
                trader=arbitrage_trader,
                type=ArbitragePositionType.LONG,
                left_type=ArbitragePositionType.LONG,
                right_type=ArbitragePositionType.SHORT,
                status=ArbitragePositionStatus.CLOSED,
                amount=Decimal("1.0"),
                left_open_price=Decimal("50000"),
                left_close_price=left_close,
                right_open_price=Decimal("50000"),
                right_close_price=right_close,
                opened_at=now - timedelta(hours=10 - i),
                closed_at=now - timedelta(hours=9 - i),
                left_total_fee=Decimal("0.50"),
                right_total_fee=Decimal("0.50"),
                close_reason=ArbitragePositionCloseReason.STRATEGY,
            )
        r2 = arbitrage_trader.get_pnl_r2()
        assert 0 < r2 < 1
