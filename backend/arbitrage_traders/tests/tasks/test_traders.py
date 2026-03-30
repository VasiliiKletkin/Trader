"""
Тесты задач Celery для ArbitrageTrader.
Фокус на корректность маршрутизации, фильтрации по статусу и query optimization.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from arbitrage_traders.models import (
    ArbitrageTrader,
    ArbitrageTraderOrder,
    ArbitrageTraderPosition,
)
from arbitrage_traders.schemas import (
    ArbitragePositionCloseReason,
    ArbitragePositionStatus,
    ArbitragePositionType,
    ArbitrageTraderStatus,
)
from arbitrage_traders.tasks.traders import (
    arbitrage_trader_reboot,
    arbitrage_traders_daily_report,
    arbitrage_traders_process_for_exchange_clients,
)
from exchange_clients.models import ExchangeClient
from exchange_clients.models import ExchangeClientOrder as ExchangeClientOrderModel
from exchange_clients.schemas import OrderSide, OrderStatus


async def _noop_coro(*a, **kw):
    pass


_NOOP = _noop_coro

# ==================== ArbitrageTrader Reboot Task Tests ====================


@pytest.mark.django_db
class TestArbitrageTraderRebootTask:
    """Тесты задачи arbitrage_trader_reboot."""

    def test_reboot_task_calls_reboot(self, arbitrage_trader):
        """Задача вызывает trader.reboot()."""
        with patch.object(ArbitrageTrader, "reboot") as mock_reboot:
            arbitrage_trader_reboot(trader_id=arbitrage_trader.pk)
            mock_reboot.assert_called_once()

    def test_reboot_task_nonexistent_trader(self):
        """Задача бросает DoesNotExist для несуществующего trader_id."""
        with pytest.raises(ArbitrageTrader.DoesNotExist):
            arbitrage_trader_reboot(trader_id=999999)

    def test_reboot_task_uses_select_related(self, arbitrage_trader):
        """Задача загружает трейдера одним SELECT с JOIN-ами."""
        with patch.object(ArbitrageTrader, "reboot"):
            with CaptureQueriesContext(connection) as q:
                arbitrage_trader_reboot(trader_id=arbitrage_trader.pk)
            select_queries = [
                query for query in q if query["sql"].upper().startswith("SELECT")
            ]
            assert len(select_queries) == 1


# ==================== ArbitrageTrader Process Task Tests ====================


@pytest.mark.django_db
class TestArbitrageTraderProcessTask:
    """Тесты задачи arbitrage_traders_process_for_exchange_clients."""

    def test_disabled_trader_not_processed(
        self, arbitrage_trader, exchange_client, right_exchange_client
    ):
        """DISABLED трейдер не обрабатывается."""
        arbitrage_trader.status = ArbitrageTraderStatus.DISABLED
        arbitrage_trader.save()

        with patch.object(ArbitrageTrader, "sync") as mock_sync:
            arbitrage_traders_process_for_exchange_clients(
                left_exchange_client_id=exchange_client.pk,
                right_exchange_client_id=right_exchange_client.pk,
                traders_ids=[arbitrage_trader.pk],
            )
            mock_sync.assert_not_called()

    def test_enabled_trader_processed(
        self,
        arbitrage_trader,
        exchange_client,
        right_exchange_client,
        exchange_candle,
        right_exchange_candle,
    ):
        """ENABLED трейдер обрабатывается и sync вызывается."""
        with (
            patch.object(ArbitrageTrader, "load"),
            patch.object(ArbitrageTrader, "sync") as mock_sync,
            patch(
                "arbitrage_traders.tasks.traders.arbitrage_trader_handle_candle_async",
                new=_NOOP,
            ),
        ):
            arbitrage_traders_process_for_exchange_clients(
                left_exchange_client_id=exchange_client.pk,
                right_exchange_client_id=right_exchange_client.pk,
                traders_ids=[arbitrage_trader.pk],
            )
            mock_sync.assert_called_once()

    def test_paused_trader_processed(
        self,
        arbitrage_trader,
        exchange_client,
        right_exchange_client,
        exchange_candle,
        right_exchange_candle,
    ):
        """PAUSED трейдер обрабатывается."""
        arbitrage_trader.status = ArbitrageTraderStatus.PAUSED
        arbitrage_trader.save()

        with (
            patch.object(ArbitrageTrader, "load"),
            patch.object(ArbitrageTrader, "sync") as mock_sync,
            patch(
                "arbitrage_traders.tasks.traders.arbitrage_trader_handle_candle_async",
                new=_NOOP,
            ),
        ):
            arbitrage_traders_process_for_exchange_clients(
                left_exchange_client_id=exchange_client.pk,
                right_exchange_client_id=right_exchange_client.pk,
                traders_ids=[arbitrage_trader.pk],
            )
            mock_sync.assert_called_once()

    def test_error_trader_processed(
        self,
        arbitrage_trader,
        exchange_client,
        right_exchange_client,
        exchange_candle,
        right_exchange_candle,
    ):
        """ERROR трейдер обрабатывается."""
        arbitrage_trader.status = ArbitrageTraderStatus.ERROR
        arbitrage_trader.save()

        with (
            patch.object(ArbitrageTrader, "load"),
            patch.object(ArbitrageTrader, "sync") as mock_sync,
            patch(
                "arbitrage_traders.tasks.traders.arbitrage_trader_handle_candle_async",
                new=_NOOP,
            ),
        ):
            arbitrage_traders_process_for_exchange_clients(
                left_exchange_client_id=exchange_client.pk,
                right_exchange_client_id=right_exchange_client.pk,
                traders_ids=[arbitrage_trader.pk],
            )
            mock_sync.assert_called_once()

    def test_rebooting_trader_excluded(
        self, arbitrage_trader, exchange_client, right_exchange_client
    ):
        """REBOOTING трейдер не обрабатывается."""
        arbitrage_trader.status = ArbitrageTraderStatus.REBOOTING
        arbitrage_trader.save()

        with patch.object(ArbitrageTrader, "sync") as mock_sync:
            arbitrage_traders_process_for_exchange_clients(
                left_exchange_client_id=exchange_client.pk,
                right_exchange_client_id=right_exchange_client.pk,
                traders_ids=[arbitrage_trader.pk],
            )
            mock_sync.assert_not_called()

    def test_handles_no_candles(
        self, arbitrage_trader, exchange_client, right_exchange_client
    ):
        """Задача не падает когда нет свечей."""
        with (
            patch.object(ArbitrageTrader, "load"),
            patch.object(ArbitrageTrader, "sync") as mock_sync,
        ):
            arbitrage_traders_process_for_exchange_clients(
                left_exchange_client_id=exchange_client.pk,
                right_exchange_client_id=right_exchange_client.pk,
                traders_ids=[arbitrage_trader.pk],
            )
            mock_sync.assert_called_once()

    def test_multiple_traders_sync_each(
        self,
        arbitrage_trader,
        exchange_client,
        right_exchange_client,
        candle_source,
        right_candle_source,
        arbitrage_strategy,
        arbitrage_risk_manager,
        exchange_candle,
        right_exchange_candle,
    ):
        """Несколько трейдеров — sync вызывается для каждого."""
        trader2 = ArbitrageTrader.objects.create(
            left_candle_source=candle_source,
            right_candle_source=right_candle_source,
            left_exchange_client=exchange_client,
            right_exchange_client=right_exchange_client,
            strategy=arbitrage_strategy,
            risk_manager=arbitrage_risk_manager,
            initial_balance=Decimal("2000"),
            status=ArbitrageTraderStatus.ENABLED,
        )
        with (
            patch.object(ArbitrageTrader, "load"),
            patch.object(ArbitrageTrader, "sync") as mock_sync,
            patch(
                "arbitrage_traders.tasks.traders.arbitrage_trader_handle_candle_async",
                new=_NOOP,
            ),
        ):
            arbitrage_traders_process_for_exchange_clients(
                left_exchange_client_id=exchange_client.pk,
                right_exchange_client_id=right_exchange_client.pk,
                traders_ids=[arbitrage_trader.pk, trader2.pk],
            )
            assert mock_sync.call_count == 2

    def test_empty_traders_list(self, exchange_client, right_exchange_client):
        """Пустой traders_ids — ничего не обрабатывается."""
        with patch.object(ArbitrageTrader, "sync") as mock_sync:
            arbitrage_traders_process_for_exchange_clients(
                left_exchange_client_id=exchange_client.pk,
                right_exchange_client_id=right_exchange_client.pk,
                traders_ids=[],
            )
            mock_sync.assert_not_called()

    def test_nonexistent_exchange_client_raises(self, arbitrage_trader):
        """Несуществующий exchange_client_id бросает DoesNotExist."""
        with pytest.raises(ExchangeClient.DoesNotExist):
            arbitrage_traders_process_for_exchange_clients(
                left_exchange_client_id=999999,
                right_exchange_client_id=999998,
                traders_ids=[arbitrage_trader.pk],
            )


# ==================== arbitrage_traders_daily_report ====================


@pytest.mark.django_db
class TestArbitrageTradersDailyReport:
    """Тесты задачи arbitrage_traders_daily_report."""

    def test_daily_report_no_orders(self):
        """Отчет без ордеров — PnL=0, fee=0."""
        with patch(
            "arbitrage_traders.tasks.traders.send_notification.delay"
        ) as mock_notify:
            arbitrage_traders_daily_report()

        mock_notify.assert_called_once()
        message = mock_notify.call_args[1]["message"]
        assert "Общий PnL: 0.00" in message
        assert "Общие комиссии: 0.00" in message

    def test_daily_report_with_closed_positions(self, arbitrage_trader, trading_pair):
        """Отчет учитывает ордера закрытых позиций за последние сутки."""
        now = datetime.now(UTC)
        position = ArbitrageTraderPosition.objects.create(
            trader=arbitrage_trader,
            left_type=ArbitragePositionType.LONG,
            right_type=ArbitragePositionType.SHORT,
            status=ArbitragePositionStatus.CLOSED,
            amount=Decimal("0.1"),
            left_open_price=Decimal("50000"),
            left_close_price=Decimal("50500"),
            right_open_price=Decimal("50100"),
            right_close_price=Decimal("49800"),
            opened_at=now - timedelta(hours=2),
            closed_at=now - timedelta(hours=1),
            left_total_fee=Decimal("5"),
            right_total_fee=Decimal("5.01"),
            close_reason=ArbitragePositionCloseReason.STRATEGY,
        )
        left_order = ExchangeClientOrderModel.objects.create(
            exchange_client=arbitrage_trader.left_exchange_client,
            exchange_order_id="report_left_1",
            trading_pair=trading_pair,
            side=OrderSide.BUY,
            status=OrderStatus.CLOSED,
            timestamp=now - timedelta(hours=2),
            amount=Decimal("0.1"),
            price=Decimal("50000"),
            cost=Decimal("5000"),
            fee=Decimal("5"),
        )
        right_order = ExchangeClientOrderModel.objects.create(
            exchange_client=arbitrage_trader.right_exchange_client,
            exchange_order_id="report_right_1",
            trading_pair=trading_pair,
            side=OrderSide.SELL,
            status=OrderStatus.CLOSED,
            timestamp=now - timedelta(hours=2),
            amount=Decimal("0.1"),
            price=Decimal("50100"),
            cost=Decimal("5010"),
            fee=Decimal("5.01"),
        )
        ArbitrageTraderOrder.objects.create(
            trader=arbitrage_trader,
            left_order=left_order,
            right_order=right_order,
            position=position,
        )

        with patch(
            "arbitrage_traders.tasks.traders.send_notification.delay"
        ) as mock_notify:
            arbitrage_traders_daily_report()

        mock_notify.assert_called_once()
        message = mock_notify.call_args[1]["message"]
        assert "Ежедневный отчет по арбитражным трейдерам" in message

    def test_daily_report_excludes_old_positions(self, arbitrage_trader, trading_pair):
        """Отчет не учитывает позиции закрытые более суток назад."""
        now = datetime.now(UTC)
        old_position = ArbitrageTraderPosition.objects.create(
            trader=arbitrage_trader,
            left_type=ArbitragePositionType.LONG,
            right_type=ArbitragePositionType.SHORT,
            status=ArbitragePositionStatus.CLOSED,
            amount=Decimal("1"),
            left_open_price=Decimal("50000"),
            left_close_price=Decimal("51000"),
            right_open_price=Decimal("50100"),
            right_close_price=Decimal("49000"),
            opened_at=now - timedelta(days=3),
            closed_at=now - timedelta(days=2),
            left_total_fee=Decimal("50"),
            right_total_fee=Decimal("50"),
            close_reason=ArbitragePositionCloseReason.STRATEGY,
        )
        left_order = ExchangeClientOrderModel.objects.create(
            exchange_client=arbitrage_trader.left_exchange_client,
            exchange_order_id="old_left_1",
            trading_pair=trading_pair,
            side=OrderSide.BUY,
            status=OrderStatus.CLOSED,
            timestamp=now - timedelta(days=3),
            amount=Decimal("1"),
            price=Decimal("50000"),
            cost=Decimal("50000"),
            fee=Decimal("50"),
        )
        right_order = ExchangeClientOrderModel.objects.create(
            exchange_client=arbitrage_trader.right_exchange_client,
            exchange_order_id="old_right_1",
            trading_pair=trading_pair,
            side=OrderSide.SELL,
            status=OrderStatus.CLOSED,
            timestamp=now - timedelta(days=3),
            amount=Decimal("1"),
            price=Decimal("50100"),
            cost=Decimal("50100"),
            fee=Decimal("50"),
        )
        ArbitrageTraderOrder.objects.create(
            trader=arbitrage_trader,
            left_order=left_order,
            right_order=right_order,
            position=old_position,
        )

        with patch(
            "arbitrage_traders.tasks.traders.send_notification.delay"
        ) as mock_notify:
            arbitrage_traders_daily_report()

        message = mock_notify.call_args[1]["message"]
        assert "Общий PnL: 0.00" in message
