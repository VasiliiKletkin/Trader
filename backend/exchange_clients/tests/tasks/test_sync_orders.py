from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest

from candle_sources.models import CandleSource
from exchange_clients.models import ExchangeClient, ExchangeClientOrder
from exchange_clients.schemas import OrderSide, OrderStatus
from exchange_clients.tasks import sync_exchange_order, sync_open_orders
from exchanges.domain import BybitExchange
from exchanges.models import Exchange, TradingPair
from exchanges.schemas import Timeframe
from traders.domain.risk_managers import SLPercentTPPercentPSAllInRiskManager
from traders.domain.strategies import MoneyFlowIndexStrategy
from traders.models import (
    RiskManager,
    Strategy,
    Trader,
    TraderOrder,
    TraderPosition,
)
from traders.schemas import PositionStatus, PositionType, TraderStatus


@pytest.fixture
def exchange() -> Exchange:
    exchange, _ = Exchange.objects.get_or_create(
        class_name=BybitExchange.__name__,
        defaults={"name": "Bybit"},
    )
    return exchange


@pytest.fixture
def trading_pair() -> TradingPair:
    pair, _ = TradingPair.objects.get_or_create(
        name="BTC/USDT",
    )
    return pair


@pytest.fixture
def exchange_client(exchange: Exchange) -> ExchangeClient:
    return ExchangeClient.objects.create(
        exchange=exchange,
        name="Test Client",
        arguments={"api_key": "test_key", "api_secret": "test_secret"},
    )


def _create_order(
    exchange_client: ExchangeClient,
    trading_pair: TradingPair,
    exchange_order_id: str,
    status: str = OrderStatus.OPENED,
) -> ExchangeClientOrder:
    return ExchangeClientOrder.objects.create(
        exchange_client=exchange_client,
        exchange_order_id=exchange_order_id,
        trading_pair=trading_pair,
        side=OrderSide.BUY,
        type="market",
        status=status,
        timestamp=datetime.now(UTC),
        amount=Decimal("0.1"),
        price=Decimal("50000.00"),
        cost=Decimal("5000.00"),
        fee=Decimal("5.00"),
    )


@pytest.fixture
def open_order(
    exchange_client: ExchangeClient, trading_pair: TradingPair
) -> ExchangeClientOrder:
    return _create_order(exchange_client, trading_pair, "order_open_1")


@pytest.fixture
def closed_order(
    exchange_client: ExchangeClient, trading_pair: TradingPair
) -> ExchangeClientOrder:
    return _create_order(
        exchange_client, trading_pair, "order_closed_1", OrderStatus.CLOSED
    )


@pytest.fixture
def trader(exchange_client: ExchangeClient, trading_pair: TradingPair) -> Trader:
    candle_source = CandleSource.objects.create(
        exchange_client=exchange_client,
        trading_pair=trading_pair,
        timeframe=Timeframe.ONE_HOUR,
    )
    strategy = Strategy.objects.create(
        name="Test Strategy",
        class_name=MoneyFlowIndexStrategy.__name__,
        arguments={"period": 14, "overbought": 80, "oversold": 20, "median": 50},
    )
    risk_manager = RiskManager.objects.create(
        name="Test RM",
        class_name=SLPercentTPPercentPSAllInRiskManager.__name__,
        arguments={"stop_loss_percent": 2.0, "take_profit_percent": 4.0},
    )
    return Trader.objects.create(
        candle_source=candle_source,
        exchange_client=exchange_client,
        strategy=strategy,
        risk_manager=risk_manager,
        initial_balance=Decimal("1000.00"),
        status=TraderStatus.ENABLED,
    )


@pytest.fixture
def trader_position(trader: Trader) -> TraderPosition:
    now = datetime.now(UTC)
    return TraderPosition.objects.create(
        trader=trader,
        type=PositionType.LONG,
        status=PositionStatus.OPENED,
        open_price=Decimal("50000.00"),
        amount=Decimal("0.1"),
        stop_loss=Decimal("49000.00"),
        take_profit=Decimal("52000.00"),
        opened_at=now,
        recalculated_at=now,
        total_fee=Decimal("5.00"),
    )


@pytest.mark.django_db
class TestSyncOpenOrders:
    def test_syncs_only_open_orders(
        self, open_order: ExchangeClientOrder, closed_order: ExchangeClientOrder
    ):
        """sync_open_orders синхронизирует только открытые ордера."""
        with patch.object(ExchangeClientOrder, "sync_from_exchange") as mock_sync:
            sync_open_orders()
            mock_sync.assert_called_once()

    def test_skips_closed_orders(self, closed_order: ExchangeClientOrder):
        """sync_open_orders не трогает закрытые ордера."""
        with patch.object(ExchangeClientOrder, "sync_from_exchange") as mock_sync:
            sync_open_orders()
            mock_sync.assert_not_called()

    def test_refreshes_trader_positions(
        self,
        open_order: ExchangeClientOrder,
        trader: Trader,
        trader_position: TraderPosition,
    ):
        """sync_open_orders обновляет связанные позиции трейдеров."""
        TraderOrder.objects.create(
            trader=trader, order=open_order, position=trader_position
        )
        with (
            patch.object(ExchangeClientOrder, "sync_from_exchange"),
            patch.object(TraderPosition, "refresh") as mock_refresh,
        ):
            sync_open_orders()
            mock_refresh.assert_called_once()

    def test_no_positions_to_refresh(self, open_order: ExchangeClientOrder):
        """sync_open_orders не падает когда нет связанных позиций."""
        with patch.object(ExchangeClientOrder, "sync_from_exchange"):
            sync_open_orders()

    def test_refreshes_only_linked_positions(
        self,
        exchange_client: ExchangeClient,
        trading_pair: TradingPair,
        trader: Trader,
        trader_position: TraderPosition,
    ):
        """sync_open_orders обновляет только позиции, связанные с открытыми ордерами."""
        linked_order = _create_order(exchange_client, trading_pair, "linked_order")
        _create_order(exchange_client, trading_pair, "unlinked_order")

        TraderOrder.objects.create(
            trader=trader, order=linked_order, position=trader_position
        )
        with (
            patch.object(ExchangeClientOrder, "sync_from_exchange"),
            patch.object(TraderPosition, "refresh") as mock_refresh,
        ):
            sync_open_orders()
            mock_refresh.assert_called_once()


@pytest.mark.django_db
class TestSyncExchangeOrder:
    def test_syncs_and_refreshes_position(
        self,
        open_order: ExchangeClientOrder,
        trader: Trader,
        trader_position: TraderPosition,
    ):
        """sync_exchange_order синхронизирует ордер и обновляет позицию."""
        TraderOrder.objects.create(
            trader=trader, order=open_order, position=trader_position
        )
        with (
            patch.object(ExchangeClientOrder, "sync_from_exchange") as mock_sync,
            patch.object(TraderPosition, "refresh") as mock_refresh,
        ):
            sync_exchange_order(open_order.pk)
            mock_sync.assert_called_once()
            mock_refresh.assert_called_once()

    def test_syncs_without_linked_position(self, open_order: ExchangeClientOrder):
        """sync_exchange_order не падает без связанной позиции."""
        with patch.object(ExchangeClientOrder, "sync_from_exchange") as mock_sync:
            sync_exchange_order(open_order.pk)
            mock_sync.assert_called_once()
