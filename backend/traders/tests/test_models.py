from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from candle_sources.models import CandleSource
from core.utils.types import PositionStatus, PositionType, Timeframe, TraderStatus
from exchange_clients.domain import ByBitExchangeClient
from exchange_clients.domain import ExchangeClientOrder as DomainTraderOrder
from exchange_clients.domain import OrderSide as DomainOrderSide
from exchange_clients.domain import OrderStatus as DomainOrderStatus
from exchange_clients.domain import OrderType as DomainOrderType
from exchanges.domain import ExchangeCandle as DomainExchangeCandle
from exchanges.domain import TradingPair as DomainTradingPair
from exchanges.models import Exchange, ExchangeCandle, TradingPair
from candle_providers.domain import ProviderCandle
from risk_managers.domain import SLPercentTPPercentPSAllInRiskManager
from risk_managers.models import RiskManager
from strategies.domain import MoneyFlowIndexStrategy
from strategies.domain import SignalType as DomainSignalType
from strategies.domain import TraderSignal as DomainTraderSignal
from strategies.models import Strategy
from traders.models import ExchangeClient, Trader, TraderPosition


@pytest.mark.django_db
def test_trader_load_instance(trader: Trader):
    domain_trader = trader.instantiate()
    with CaptureQueriesContext(connection) as queries:
        trader.load(domain_trader)
    assert len(queries) == 2


@pytest.mark.django_db
def test_trader_sync_instance(trader: Trader):
    candle = ExchangeCandle.objects.create(
        exchange=trader.exchange_client.exchange,
        timeframe=trader.timeframe,
        trading_pair=trader.trading_pair,
        timestamp=timezone.now(),
        open=Decimal("100.0"),
        high=Decimal("101.0"),
        low=Decimal("99.0"),
        close=Decimal("100.5"),
        volume=Decimal("10.0"),
    )
    domain_candle = candle.instantiate()
    provider_candle = ProviderCandle(
        dt_unix=domain_candle.dt_unix,
        open=domain_candle.open,
        high=domain_candle.high,
        low=domain_candle.low,
        close=domain_candle.close,
        volume=domain_candle.volume,
        first_candle=domain_candle,
        second_candle=None,
    )

    domain_trader = trader.instantiate()
    domain_signal = DomainTraderSignal(
        id=None,
        timestamp=timezone.now(),
        price=Decimal("100.5"),
        candle=provider_candle,
        type=DomainSignalType.WAIT,
        data={},
    )
    domain_trader.signals.append(domain_signal)

    position = TraderPosition.objects.create(
        trader=trader,
        type=PositionType.LONG,
        status=PositionStatus.OPENED,
        amount=Decimal("0.1"),
        open_price=Decimal("100.5"),
        close_price=None,
        stop_loss=None,
        take_profit=None,
        opened_at=timezone.now(),
        closed_at=None,
        recalculated_at=None,
        close_reason=None,
        total_fee=Decimal("0.00"),
    )
    domain_position = position.instantiate()
    domain_order = DomainTraderOrder(
        timestamp=timezone.now(),
        status=DomainOrderStatus.OPENED,
        trading_pair=domain_trader.trading_pair,
        exchange_order_id="order_123",
        type=DomainOrderType.MARKET,
        side=DomainOrderSide.BUY,
        price=Decimal("100.5"),
        amount=Decimal("0.1"),
        fee=Decimal("0.01"),
        cost=Decimal("10.05"),
    )
    domain_position.orders.append(domain_order)
    domain_trader.positions.append(domain_position)

    with CaptureQueriesContext(connection) as queries:
        trader.sync(domain_trader)

    assert len(queries) == 8


@pytest.mark.django_db
def test_trader_instantiate(trader: Trader):
    with CaptureQueriesContext(connection) as queries:
        trader.instantiate()
    assert len(queries) == 1


@pytest.mark.django_db
def test_trader_reboot(trader: Trader):
    with CaptureQueriesContext(connection) as queries:
        trader.reboot()
    assert len(queries) == 7


@pytest.mark.django_db
def test_trader_get_balance(trader: Trader):
    trader.use_fixed_balance = False
    with CaptureQueriesContext(connection) as queries:
        trader.get_balance()
    assert len(queries) == 1


@pytest.mark.django_db
def test_domain_exchange_client_instantiate(trader: Trader):
    with CaptureQueriesContext(connection) as queries:
        trader.exchange_client.instantiate()
    assert len(queries) == 0
