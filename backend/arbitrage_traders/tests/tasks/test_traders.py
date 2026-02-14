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

from arbitrage_traders.models import ArbitrageTrader
from arbitrage_traders.schemas import ArbitrageTraderStatus
from arbitrage_traders.tasks.traders import (
    arbitrage_trader_reboot,
    arbitrage_traders_process_for_exchange_clients,
)
from exchange_clients.models import ExchangeClient
from exchanges.models import ExchangeCandle
from exchanges.schemas import Timeframe

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
            patch("arbitrage_traders.tasks.traders.asyncio.run"),
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
            patch("arbitrage_traders.tasks.traders.asyncio.run"),
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
            patch("arbitrage_traders.tasks.traders.asyncio.run"),
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

        with (
            patch.object(ArbitrageTrader, "sync") as mock_sync,
            patch("arbitrage_traders.tasks.traders.asyncio.run"),
        ):
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
            patch("arbitrage_traders.tasks.traders.asyncio.run"),
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
            patch("arbitrage_traders.tasks.traders.asyncio.run"),
        ):
            arbitrage_traders_process_for_exchange_clients(
                left_exchange_client_id=exchange_client.pk,
                right_exchange_client_id=right_exchange_client.pk,
                traders_ids=[arbitrage_trader.pk, trader2.pk],
            )
            assert mock_sync.call_count == 2

    def test_empty_traders_list(self, exchange_client, right_exchange_client):
        """Пустой traders_ids — asyncio.run не вызывается."""
        with patch("arbitrage_traders.tasks.traders.asyncio.run") as mock_run:
            arbitrage_traders_process_for_exchange_clients(
                left_exchange_client_id=exchange_client.pk,
                right_exchange_client_id=right_exchange_client.pk,
                traders_ids=[],
            )
            mock_run.assert_not_called()

    def test_nonexistent_exchange_client_raises(self, arbitrage_trader):
        """Несуществующий exchange_client_id бросает DoesNotExist."""
        with pytest.raises(ExchangeClient.DoesNotExist):
            arbitrage_traders_process_for_exchange_clients(
                left_exchange_client_id=999999,
                right_exchange_client_id=999998,
                traders_ids=[arbitrage_trader.pk],
            )

    def test_existing_signal_routes_to_check_positions(
        self,
        arbitrage_trader,
        exchange_client,
        right_exchange_client,
        exchange,
        right_exchange,
        trading_pair,
        arbitrage_signal,
        exchange_candle,
        right_exchange_candle,
    ):
        """Существующий сигнал на предыдущую свечу → маршрут check_opened_positions."""
        now = datetime.now(UTC)
        # Создаём более новые свечи, чтобы get_last_candles вернул 2 штуки
        ExchangeCandle.objects.create(
            exchange=exchange,
            trading_pair=trading_pair,
            timeframe=Timeframe.ONE_HOUR,
            timestamp=now + timedelta(hours=1),
            open=Decimal("51000"),
            high=Decimal("52000"),
            low=Decimal("50000"),
            close=Decimal("51500"),
            volume=Decimal("200"),
        )
        ExchangeCandle.objects.create(
            exchange=right_exchange,
            trading_pair=trading_pair,
            timeframe=Timeframe.ONE_HOUR,
            timestamp=now + timedelta(hours=1),
            open=Decimal("51100"),
            high=Decimal("52100"),
            low=Decimal("50100"),
            close=Decimal("51600"),
            volume=Decimal("200"),
        )
        # Сигнал привязан к timestamp текущей exchange_candle
        exchange_candle.timestamp = arbitrage_signal.timestamp
        exchange_candle.save()

        with (
            patch.object(ArbitrageTrader, "load"),
            patch.object(ArbitrageTrader, "sync"),
            patch("arbitrage_traders.tasks.traders.asyncio.run") as mock_run,
        ):
            arbitrage_traders_process_for_exchange_clients(
                left_exchange_client_id=exchange_client.pk,
                right_exchange_client_id=right_exchange_client.pk,
                traders_ids=[arbitrage_trader.pk],
            )
            # asyncio.run должен быть вызван (есть задачи для gather)
            mock_run.assert_called_once()
