from decimal import Decimal
from typing import List

import pytest
from core.utils.types import PositionStatus, PositionType, Timeframe, TraderStatus
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from exchange_clients.domain import ByBitExchangeClient
from exchange_clients.domain import ExchangeClientOrder as DomainTraderOrder
from exchange_clients.domain import OrderSide as DomainOrderSide
from exchange_clients.domain import OrderType as DomainOrderType
from exchange_clients.models import ExchangeClientCandleSource
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
from traders.tasks import (
    trader_reboot,
    traders_process_for_exchange_client,
)

from exchange_clients.domain import OrderStatus as DomainOrderStatus


def get_optimized_trader_queryset():

    return Trader.objects.select_related(
        "exchange_client",
        "exchange_client__exchange",
        "exchange_client__proxy",
        "candle_source",
        "risk_manager",
        "strategy",
    ).prefetch_related(
        "candle_source__exchange_client_candle_sources",
        "candle_source__exchange_client_candle_sources__trading_pair",
        "candle_source__exchange_client_candle_sources__trading_pair__exchangetradingpair_set",
        "candle_source__exchange_client_candle_sources__exchange_client",
        "candle_source__exchange_client_candle_sources__exchange_client__exchange",
    )


@pytest.mark.django_db
def test_trader_instantiate(trader: Trader):
    """
    Тест проверяет оптимизацию запросов при инстанциации трейдера.

    Оптимизации:
    - Добавлен exchange_client__proxy в select_related для избежания дополнительного запроса
    - Все связи загружаются одним запросом через select_related/prefetch_related
    - Используется helper функция get_optimized_trader_queryset()
    """
    with CaptureQueriesContext(connection) as queries:
        tr = get_optimized_trader_queryset().get(id=trader.pk)
        tr.instantiate()

    assert len(queries) == 6


@pytest.mark.django_db
def test_candle_source_instantiate(trader: Trader):
    """
    Тест проверяет количество запросов при вызове candle_source.instantiate().

    candle_source.instantiate() без параметров start_date/end_date делает 0 запросов,
    так как использует prefetch кеш и возвращает генераторы.

    Реальные запросы к БД выполняются при итерации по генератору свечей.
    """
    tr = get_optimized_trader_queryset().get(id=trader.pk)
    with CaptureQueriesContext(connection) as queries:
        candle_source = tr.candle_source.instantiate()
    assert len(queries) == 0
    with CaptureQueriesContext(connection) as queries:
        list(candle_source.get_candle_iterator())
    assert len(queries) in [1, 2]


@pytest.mark.django_db
def test_trader_reboot_calls_reboot(trader: Trader):
    """
    Тест проверяет оптимизацию запросов при перезагрузке трейдера.

    Оптимизации:
    - Используется get_optimized_trader_queryset() в tasks.py
    - Применены оптимизации cached_property в модели Trader
    - instantiate() выполняет только 6 запросов вместо 11

    Структура запросов (12 total):
    - 6 запросов: trader.instantiate() (оптимизировано!)
    - 2 запроса: candle_source.instantiate() для загрузки свечей (оптимизировано!)
    - 2 запроса: clear_all_data() (DELETE операции)
    - 2 запроса: save() операции (UPDATE статуса)
    """
    with CaptureQueriesContext(connection) as queries:
        trader_reboot(trader_id=trader.pk)
    assert len(queries) == 12


@pytest.mark.django_db
def test_traders_process_for_exchange_client_one_trader(
    exchange_client: ExchangeClient,
    strategy: Strategy,
    candle_source: ExchangeClientCandleSource,
    risk_manager: RiskManager,
):
    trader = Trader.objects.create(
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
    with CaptureQueriesContext(connection) as queries:
        traders_process_for_exchange_client(
            exchange_client_id=exchange_client.pk,
            traders_ids=[trader.pk],
        )
    assert len(queries) == 10


@pytest.mark.django_db
def test_traders_process_for_exchange_client_two_trader(
    exchange_client: ExchangeClient,
    strategy: Strategy,
    candle_source: ExchangeClientCandleSource,
    risk_manager: RiskManager,
):
    trader1 = Trader.objects.create(
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
    trader2 = Trader.objects.create(
        exchange_client=exchange_client,
        candle_source=candle_source,
        strategy=strategy,
        risk_manager=risk_manager,
        use_fixed_balance=True,
        initial_balance=Decimal("100.00"),
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
    with CaptureQueriesContext(connection) as queries:
        traders_process_for_exchange_client(
            exchange_client_id=exchange_client.pk,
            traders_ids=[trader1.pk, trader2.pk],
        )
    assert len(queries) == 12


@pytest.mark.django_db
def test_traders_process_for_exchange_client_three_trader(
    exchange_client: ExchangeClient,
    strategy: Strategy,
    candle_source: ExchangeClientCandleSource,
    risk_manager: RiskManager,
):
    trader1 = Trader.objects.create(
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
    trader2 = Trader.objects.create(
        exchange_client=exchange_client,
        candle_source=candle_source,
        strategy=strategy,
        risk_manager=risk_manager,
        use_fixed_balance=True,
        initial_balance=Decimal("100.00"),
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
    trader3 = Trader.objects.create(
        exchange_client=exchange_client,
        candle_source=candle_source,
        strategy=strategy,
        risk_manager=risk_manager,
        use_fixed_balance=True,
        initial_balance=Decimal("10.00"),
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
    with CaptureQueriesContext(connection) as queries:
        traders_process_for_exchange_client(
            exchange_client_id=exchange_client.pk,
            traders_ids=[trader1.pk, trader2.pk, trader3.pk],
        )
    assert len(queries) == 14