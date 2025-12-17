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

from backend.exchange_clients.domain import OrderStatus as DomainOrderStatus


@pytest.mark.django_db
def test_trader_reboot_calls_reboot(trader: Trader):
    with CaptureQueriesContext(connection) as queries:
        trader_reboot(trader_id=trader.pk)
    assert len(queries) == 8


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
    assert len(queries) == 6


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
    assert len(queries) == 9


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
    assert len(queries) == 12


# @pytest.mark.django_db
# def test_traders_daily_report_sends_notification(monkeypatch):
#     now = timezone.now()
#     with patch("traders.tasks.TraderOrder.objects.filter") as filter_mock, patch(
#         "traders.tasks.send_notification.delay"
#     ) as notify_mock:
#         qs = MagicMock()
#         filter_mock.return_value = qs
#         qs.aggregate.return_value = {"pnl": Decimal("100.00"), "fee": Decimal("5.00")}
#         with patch(
#             "traders.tasks.dt_str", side_effect=lambda dt: dt.strftime("%Y-%m-%d")
#         ):
#             traders_daily_report()
#         notify_mock.assert_called_once()
#         msg = notify_mock.call_args[1]["message"]
#         assert "Общий PnL" in msg
#         assert "Чистая прибыль" in msg


# @pytest.mark.django_db
# def test_traders_process_for_exchange_client(monkeypatch):
#     exchange_client_id = 1
#     traders_ids = [1, 2]
#     fake_exchange_client = MagicMock()
#     fake_trader = MagicMock()
#     fake_trader.candle_source = MagicMock()
#     fake_trader.candle_source.pk = 10
#     fake_trader.candle_source.get_last_candles.return_value = [MagicMock(), MagicMock()]
#     fake_trader.status = "ENABLED"
#     fake_trader.has_existing_signal.return_value = True
#     fake_trader.instantiate.return_value = MagicMock()
#     fake_trader.load.return_value = None
#     with patch(
#         "traders.tasks.ExchangeClient.active_objects.select_related"
#     ) as ec_sel, patch("traders.tasks.Trader.objects.filter") as trader_filter, patch(
#         "traders.tasks.trader_check_opened_positions_async"
#     ) as check_async, patch(
#         "traders.tasks.trader_handle_candle_async"
#     ) as handle_async, patch(
#         "traders.tasks.run_tasks_with_exchange_client"
#     ) as run_tasks, patch(
#         "traders.tasks.send_notification.delay"
#     ):
#         ec_sel.return_value.get.return_value = fake_exchange_client
#         trader_filter.return_value.select_related.return_value = [fake_trader]
#         check_async.return_value = MagicMock()
#         run_tasks.return_value = None
#         traders_process_for_exchange_client(exchange_client_id, traders_ids)
#         assert check_async.called or handle_async.called
#         assert run_tasks.called
