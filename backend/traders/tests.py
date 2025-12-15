import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from decimal import Decimal

from exchange_clients.models import ExchangeClientCandleSource
from exchanges.models import TradingPair
from strategies.domain import MoneyFlowIndexStrategy
from strategies.models import Strategy
from core.utils.types import Timeframe, TraderStatus
from exchanges.models import Exchange
import traders.tasks as tasks
from traders.models import Trader, ExchangeClient
from risk_managers.models import RiskManager
import django
from django.db import connection
from risk_managers.domain import SLPercentTPPercentPSAllInRiskManager


@pytest.fixture
def exchange(db):
    return Exchange.objects.create(
        name="Test Exchange",
    )


@pytest.fixture
def exchange_client(db, exchange):
    return ExchangeClient.objects.create(
        exchange=exchange,
        api_key="test_key",
        api_secret="test_secret",
        name="Test EC",
    )


def trading_pair(db):
    return TradingPair.objects.create(
        name="BTC/USDT",
        symbol="BTC/USDT:USDT",
        min_amount=Decimal("0.001"),
        max_amount=Decimal("1000000"),
        fee_percent=Decimal("0.1"),
    )


def candle_source(db, exchange_client, trading_pair):
    return ExchangeClientCandleSource.objects.create(
        exchange_client=exchange_client,
        trading_pair=trading_pair,
        timeframe=Timeframe.ONE_HOUR,
    )


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
    exchange_client,
    candle_source,
    strategy,
    risk_manager,
):
    return Trader.objects.create(
        exchange_client=exchange_client,
        candle_source=candle_source,
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


@pytest.mark.django_db
def test_trader_reboot_query_count(trader):
    """
    Проверяет, сколько SQL-запросов выполняется при вызове reboot у Trader.
    """
    with django.test.utils.CaptureQueriesContext(connection) as queries:
        trader.reboot()
    print(f"SQL queries count: {len(queries)}")
    # Можно добавить assert, если ожидаете конкретное число запросов:
    # assert len(queries) <= EXPECTED_COUNT
