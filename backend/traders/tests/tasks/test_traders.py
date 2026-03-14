"""
Тесты задач Celery для Trader.
Фокус на корректность маршрутизации, фильтрации по статусу и query optimization.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from exchange_clients.models import ExchangeClient, ExchangeClientOrder
from exchange_clients.schemas import OrderSide, OrderStatus
from traders.models import Trader, TraderOrder, TraderPosition
from traders.schemas import (
    PositionCloseReason,
    PositionStatus,
    PositionType,
    TraderStatus,
)
from traders.tasks import traders as trader_tasks
from traders.tasks.traders import (
    dispatch_traders_for_sources,
    trader_reboot,
    traders_daily_report,
    traders_process_for_exchange_client,
)

_NOOP = lambda *a, **kw: None  # noqa: E731


# ==================== traders_process_for_exchange_client ====================


@pytest.mark.django_db
class TestTradersProcessForExchangeClient:
    """Тесты задачи traders_process_for_exchange_client."""

    def test_disabled_trader_not_processed(self, trader, exchange_client):
        """DISABLED трейдер не обрабатывается."""
        trader.status = TraderStatus.DISABLED
        trader.save()

        with patch.object(Trader, "sync") as mock_sync:
            traders_process_for_exchange_client(
                exchange_client_id=exchange_client.pk,
                traders_ids=[trader.pk],
            )
            mock_sync.assert_not_called()

    def test_enabled_trader_processed(self, trader, exchange_client, exchange_candle):
        """ENABLED трейдер обрабатывается и sync вызывается."""
        with (
            patch.object(Trader, "load"),
            patch.object(Trader, "sync") as mock_sync,
            patch(
                "traders.tasks.traders.trader_handle_candle_async",
                new=_NOOP,
            ),
            patch(
                "traders.tasks.traders.asyncio.run",
                side_effect=lambda coro: (
                    coro.close() if hasattr(coro, "close") else None
                ),
            ),
        ):
            traders_process_for_exchange_client(
                exchange_client_id=exchange_client.pk,
                traders_ids=[trader.pk],
            )
            mock_sync.assert_called_once()

    def test_paused_trader_processed(self, trader, exchange_client, exchange_candle):
        """PAUSED трейдер обрабатывается."""
        trader.status = TraderStatus.PAUSED
        trader.save()

        with (
            patch.object(Trader, "load"),
            patch.object(Trader, "sync") as mock_sync,
            patch(
                "traders.tasks.traders.trader_handle_candle_async",
                new=_NOOP,
            ),
            patch(
                "traders.tasks.traders.asyncio.run",
                side_effect=lambda coro: (
                    coro.close() if hasattr(coro, "close") else None
                ),
            ),
        ):
            traders_process_for_exchange_client(
                exchange_client_id=exchange_client.pk,
                traders_ids=[trader.pk],
            )
            mock_sync.assert_called_once()

    def test_error_trader_processed(self, trader, exchange_client, exchange_candle):
        """ERROR трейдер обрабатывается."""
        trader.status = TraderStatus.ERROR
        trader.save()

        with (
            patch.object(Trader, "load"),
            patch.object(Trader, "sync") as mock_sync,
            patch(
                "traders.tasks.traders.trader_handle_candle_async",
                new=_NOOP,
            ),
            patch(
                "traders.tasks.traders.asyncio.run",
                side_effect=lambda coro: (
                    coro.close() if hasattr(coro, "close") else None
                ),
            ),
        ):
            traders_process_for_exchange_client(
                exchange_client_id=exchange_client.pk,
                traders_ids=[trader.pk],
            )
            mock_sync.assert_called_once()

    def test_rebooting_trader_excluded(self, trader, exchange_client):
        """REBOOTING трейдер не обрабатывается."""
        trader.status = TraderStatus.REBOOTING
        trader.save()

        with patch.object(Trader, "sync") as mock_sync:
            traders_process_for_exchange_client(
                exchange_client_id=exchange_client.pk,
                traders_ids=[trader.pk],
            )
            mock_sync.assert_not_called()

    def test_empty_traders_list(self, exchange_client):
        """Пустой traders_ids — asyncio.run вызывается для закрытия клиента."""
        with patch(
            "traders.tasks.traders.asyncio.run",
            side_effect=lambda coro: coro.close() if hasattr(coro, "close") else None,
        ) as mock_run:
            traders_process_for_exchange_client(
                exchange_client_id=exchange_client.pk,
                traders_ids=[],
            )
            mock_run.assert_called_once()

    def test_nonexistent_exchange_client_raises(self, trader):
        """Несуществующий exchange_client_id бросает DoesNotExist."""
        with pytest.raises(ExchangeClient.DoesNotExist):
            traders_process_for_exchange_client(
                exchange_client_id=999999,
                traders_ids=[trader.pk],
            )

    def test_multiple_traders_sync_each(
        self,
        trader,
        exchange_client,
        candle_source,
        strategy,
        risk_manager,
        exchange_candle,
    ):
        """Несколько трейдеров — sync вызывается для каждого."""
        trader2 = Trader.objects.create(
            candle_source=candle_source,
            exchange_client=exchange_client,
            strategy=strategy,
            risk_manager=risk_manager,
            initial_balance=Decimal("2000"),
            status=TraderStatus.ENABLED,
        )
        with (
            patch.object(Trader, "load"),
            patch.object(Trader, "sync") as mock_sync,
            patch(
                "traders.tasks.traders.trader_handle_candle_async",
                new=_NOOP,
            ),
            patch(
                "traders.tasks.traders.asyncio.run",
                side_effect=lambda coro: (
                    coro.close() if hasattr(coro, "close") else None
                ),
            ),
        ):
            traders_process_for_exchange_client(
                exchange_client_id=exchange_client.pk,
                traders_ids=[trader.pk, trader2.pk],
            )
            assert mock_sync.call_count == 2

    def test_handles_no_candles(self, trader, exchange_client):
        """Задача не падает когда нет свечей."""
        with (
            patch.object(Trader, "load"),
            patch.object(Trader, "sync") as mock_sync,
            patch(
                "traders.tasks.traders.trader_handle_candle_async",
                new=_NOOP,
            ),
            patch(
                "traders.tasks.traders.asyncio.run",
                side_effect=lambda coro: (
                    coro.close() if hasattr(coro, "close") else None
                ),
            ),
        ):
            traders_process_for_exchange_client(
                exchange_client_id=exchange_client.pk,
                traders_ids=[trader.pk],
            )
            mock_sync.assert_called_once()


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
    def __init__(self, traders):
        self._traders = traders

    def select_related(self, *args, **kwargs):
        return self

    def iterator(self):
        return iter(self._traders)


def _make_trader(pk: int, exchange_client_id: int):
    exchange_client = SimpleNamespace(pk=exchange_client_id)
    return SimpleNamespace(pk=pk, exchange_client=exchange_client)


class TestDispatchTradersForSources:
    def test_groups_by_exchange_client(self, monkeypatch):
        traders = [
            _make_trader(1, 10),
            _make_trader(2, 20),
            _make_trader(3, 10),
        ]

        monkeypatch.setattr(
            trader_tasks.Trader.objects,
            "filter",
            lambda *args, **kwargs: _FakeQuerySet(traders),
        )

        captured = {"items": None, "applied": False}

        def fake_group(signatures):
            captured["items"] = list(signatures)

            class Dummy:
                def apply_async(self):
                    captured["applied"] = True

            return Dummy()

        monkeypatch.setattr("traders.tasks.traders.group", fake_group)
        monkeypatch.setattr(
            trader_tasks.traders_process_for_exchange_client,
            "s",
            lambda exchange_client_id, traders_ids: (
                exchange_client_id,
                traders_ids,
            ),
        )

        dispatch_traders_for_sources(source_ids=[1])

        assert captured["applied"] is True
        grouped = dict(captured["items"])
        assert grouped[10] == [1, 3]
        assert grouped[20] == [2]

    def test_no_traders(self, monkeypatch):
        monkeypatch.setattr(
            trader_tasks.Trader.objects,
            "filter",
            lambda *args, **kwargs: _FakeQuerySet([]),
        )
        group_mock = MagicMock()
        monkeypatch.setattr("traders.tasks.traders.group", group_mock)

        dispatch_traders_for_sources(source_ids=[1])

        group_mock.assert_not_called()
