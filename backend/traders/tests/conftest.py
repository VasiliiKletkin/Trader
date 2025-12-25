from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from candle_providers.models import CandleProvider
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
from risk_managers.domain import SLPercentTPPercentPSAllInRiskManager
from risk_managers.models import RiskManager
from strategies.domain import MoneyFlowIndexStrategy
from strategies.domain import SignalType as DomainSignalType
from strategies.domain import TraderSignal as DomainTraderSignal
from strategies.models import Strategy
from traders.models import ExchangeClient, Trader, TraderPosition


@pytest.fixture
def exchange(db):
    return Exchange.objects.create(
        name="Test Exchange",
        class_name=ByBitExchangeClient.__name__,
    )


@pytest.fixture
def exchange_client(db, exchange: Exchange):
    return ExchangeClient.objects.create(
        exchange=exchange,
        api_key="test_key",
        api_secret="test_secret",
        name="Test EC",
    )


@pytest.fixture
def trading_pair(db):
    return TradingPair.objects.create(
        name="BTC/USDT",
        symbol="BTC/USDT:USDT",
        min_amount=Decimal("0.001"),
        max_amount=Decimal("1000000"),
        fee_percent=Decimal("0.1"),
    )


@pytest.fixture
def candle_provider(db, exchange_client: ExchangeClient, trading_pair: TradingPair):
    eccs = CandleSource.objects.create(
        exchange_client=exchange_client,
        trading_pair=trading_pair,
        timeframe=Timeframe.ONE_HOUR,
    )
    return CandleProvider.objects.create(
        class_name="PlainCandleProvider",
        primary_source=eccs,
    )


@pytest.fixture
def strategy(db):
    return Strategy.objects.create(
        name="Test Strategy",
        class_name=MoneyFlowIndexStrategy.__name__,
        arguments={
            "period": MoneyFlowIndexStrategy.PERIOD_DEFAULT,
            "overbought": MoneyFlowIndexStrategy.OVERBOUGHT_DEFAULT,
            "oversold": MoneyFlowIndexStrategy.OVERSOLD_DEFAULT,
            "median": MoneyFlowIndexStrategy.MEDIAN_DEFAULT,
        },
    )


@pytest.fixture
def risk_manager(db):
    return RiskManager.objects.create(
        name="Test Risk Manager",
        class_name=SLPercentTPPercentPSAllInRiskManager.__name__,
        arguments={
            "stop_loss_percent": SLPercentTPPercentPSAllInRiskManager.STOP_LOSS_PERCENT_DEFAULT,
            "take_profit_percent": SLPercentTPPercentPSAllInRiskManager.TAKE_PROFIT_PERCENT_DEFAULT,
        },
    )


@pytest.fixture
def trader(
    db,
    exchange_client: ExchangeClient,
    candle_provider: CandleProvider,
    strategy: Strategy,
    risk_manager: RiskManager,
):
    return Trader.objects.create(
        exchange_client=exchange_client,
        candle_provider=candle_provider,
        strategy=strategy,
        risk_manager=risk_manager,
        use_fixed_balance=True,
        initial_balance=Decimal("1000.00"),
        check_drawdown=False,
        max_drawdown_pct=Decimal("0.0"),
        create_new_orders=True,
        max_positions_count=1,
        close_position_by_opposite_signal=True,
        close_position_by_strategy=True,
        close_position_by_stop_loss=True,
        close_position_by_take_profit=True,
        trail_stop_enabled=True,
        status=TraderStatus.ENABLED,
    )
