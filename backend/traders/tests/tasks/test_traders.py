"""
Тесты задач Celery для Trader.
Фокус на корректность маршрутизации, фильтрации по статусу и query optimization.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from exchange_clients.models import ExchangeClientOrder
from exchange_clients.schemas import OrderSide, OrderStatus
from traders.models import Trader, TraderOrder, TraderPosition
from traders.schemas import (
    PositionCloseReason,
    PositionStatus,
    PositionType,
)
from traders.tasks import traders as trader_tasks
from traders.tasks.traders import (
    dispatch_traders_for_sources,
    trader_reboot,
    traders_daily_report,
)

# ==================== trader_reboot ====================


@pytest.mark.django_db
class TestTraderRebootTask:
    """Тесты задачи trader_reboot."""

    def test_reboot_task_calls_reboot(self, trader):
        """Задача вызывает trader.reboot()."""
        with patch.object(Trader, "reboot") as mock_reboot:
            trader_reboot(trader_id=trader.pk)
            mock_reboot.assert_called_once()

    def test_reboot_task_nonexistent_trader(self):
        """Задача бросает DoesNotExist для несуществующего trader_id."""
        with pytest.raises(Trader.DoesNotExist):
            trader_reboot(trader_id=999999)

    def test_reboot_task_uses_select_related(self, trader):
        """Задача загружает трейдера одним SELECT с JOIN-ами."""
        with patch.object(Trader, "reboot"):
            with CaptureQueriesContext(connection) as q:
                trader_reboot(trader_id=trader.pk)
            select_queries = [
                query for query in q if query["sql"].upper().startswith("SELECT")
            ]
            assert len(select_queries) == 1


# ==================== traders_daily_report ====================


@pytest.mark.django_db
class TestTradersDailyReport:
    """Тесты задачи traders_daily_report."""

    def test_daily_report_no_orders(self):
        """Отчет без ордеров — PnL=0, fee=0."""
        with patch("traders.tasks.traders.send_notification.delay") as mock_notify:
            traders_daily_report()

        mock_notify.assert_called_once()
        message = mock_notify.call_args[1]["message"]
        assert "0.00" in message

    def test_daily_report_with_closed_positions(
        self, trader, exchange_client, trading_pair
    ):
        """Отчет учитывает ордера закрытых позиций за последние сутки."""
        now = datetime.now(UTC)
        position = TraderPosition.objects.create(
            trader=trader,
            type=PositionType.LONG,
            status=PositionStatus.CLOSED,
            open_price=Decimal("50000"),
            close_price=Decimal("51000"),
            amount=Decimal("0.1"),
            opened_at=now - timedelta(hours=2),
            closed_at=now - timedelta(hours=1),
            recalculated_at=now,
            total_fee=Decimal("10"),
            close_reason=PositionCloseReason.TAKE_PROFIT,
        )
        buy_order = ExchangeClientOrder.objects.create(
            exchange_client=exchange_client,
            exchange_order_id="daily_buy_1",
            trading_pair=trading_pair,
            side=OrderSide.BUY,
            status=OrderStatus.CLOSED,
            timestamp=now - timedelta(hours=2),
            amount=Decimal("0.1"),
            price=Decimal("50000"),
            cost=Decimal("5000"),
            fee=Decimal("5"),
        )
        sell_order = ExchangeClientOrder.objects.create(
            exchange_client=exchange_client,
            exchange_order_id="daily_sell_1",
            trading_pair=trading_pair,
            side=OrderSide.SELL,
            status=OrderStatus.CLOSED,
            timestamp=now - timedelta(hours=1),
            amount=Decimal("0.1"),
            price=Decimal("51000"),
            cost=Decimal("5100"),
            fee=Decimal("5.10"),
        )
        TraderOrder.objects.create(trader=trader, order=buy_order, position=position)
        TraderOrder.objects.create(trader=trader, order=sell_order, position=position)

        with patch("traders.tasks.traders.send_notification.delay") as mock_notify:
            traders_daily_report()

        mock_notify.assert_called_once()
        message = mock_notify.call_args[1]["message"]
        assert "Ежедневный отчет" in message

    def test_daily_report_excludes_old_positions(
        self, trader, exchange_client, trading_pair
    ):
        """Отчет не учитывает позиции закрытые более суток назад."""
        now = datetime.now(UTC)
        old_position = TraderPosition.objects.create(
            trader=trader,
            type=PositionType.LONG,
            status=PositionStatus.CLOSED,
            open_price=Decimal("50000"),
            close_price=Decimal("60000"),
            amount=Decimal("1"),
            opened_at=now - timedelta(days=3),
            closed_at=now - timedelta(days=2),
            recalculated_at=now,
            total_fee=Decimal("10"),
            close_reason=PositionCloseReason.TAKE_PROFIT,
        )
        buy_order = ExchangeClientOrder.objects.create(
            exchange_client=exchange_client,
            exchange_order_id="old_buy_1",
            trading_pair=trading_pair,
            side=OrderSide.BUY,
            status=OrderStatus.CLOSED,
            timestamp=now - timedelta(days=3),
            amount=Decimal("1"),
            price=Decimal("50000"),
            cost=Decimal("50000"),
            fee=Decimal("50"),
        )
        sell_order = ExchangeClientOrder.objects.create(
            exchange_client=exchange_client,
            exchange_order_id="old_sell_1",
            trading_pair=trading_pair,
            side=OrderSide.SELL,
            status=OrderStatus.CLOSED,
            timestamp=now - timedelta(days=2),
            amount=Decimal("1"),
            price=Decimal("60000"),
            cost=Decimal("60000"),
            fee=Decimal("60"),
        )
        TraderOrder.objects.create(
            trader=trader, order=buy_order, position=old_position
        )
        TraderOrder.objects.create(
            trader=trader, order=sell_order, position=old_position
        )

        with patch("traders.tasks.traders.send_notification.delay") as mock_notify:
            traders_daily_report()

        message = mock_notify.call_args[1]["message"]
        # PnL должен быть 0, т.к. позиция закрыта 2 дня назад
        assert "Общий PnL: 0.00" in message


# ==================== dispatch_traders_for_sources ====================


class _FakeQuerySet:
    def __init__(self, ids):
        self._ids = ids

    def filter(self, *args, **kwargs):
        return self

    def values_list(self, *args, **kwargs):
        return self._ids


class TestDispatchTradersForSources:
    def test_dispatches_trader_process(self, monkeypatch):
        monkeypatch.setattr(
            trader_tasks.Trader.objects,
            "filter",
            lambda *args, **kwargs: _FakeQuerySet([1, 2, 3]),
        )

        group_mock = MagicMock()
        monkeypatch.setattr(trader_tasks, "group", group_mock)

        dispatch_traders_for_sources(source_ids=[1])

        group_mock.assert_called_once()
        group_mock.return_value.apply_async.assert_called_once()

    def test_no_traders(self, monkeypatch):
        monkeypatch.setattr(
            trader_tasks.Trader.objects,
            "filter",
            lambda *args, **kwargs: _FakeQuerySet([]),
        )

        group_mock = MagicMock()
        monkeypatch.setattr(trader_tasks, "group", group_mock)

        dispatch_traders_for_sources(source_ids=[1])

        group_mock.assert_not_called()
