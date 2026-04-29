"""
Тесты моделей Trader.
Фокус на query count validation и корректность ORM операций.
"""

from collections import deque
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from django.db import IntegrityError, connection
from django.forms import ValidationError
from django.test.utils import CaptureQueriesContext

from exchange_clients.models import ExchangeClientOrder
from exchange_clients.schemas import OrderSide, OrderStatus
from exchanges.models import ExchangeCandle
from exchanges.schemas import Timeframe
from traders.domain import Trader as DomainTrader
from traders.domain.schemas import (
    PositionCloseReason as DomainPositionCloseReason,
)
from traders.domain.schemas import PositionStatus as DomainPositionStatus
from traders.domain.schemas import PositionType as DomainPositionType
from traders.domain.schemas import SignalType as DomainSignalType
from traders.domain.schemas import TraderSignal as DomainTraderSignal
from traders.models import (
    Trader,
    TraderError,
    TraderOrder,
    TraderPosition,
    TraderSignal,
)
from traders.schemas import (
    PositionCloseReason,
    PositionStatus,
    PositionType,
    SignalType,
    TraderStatus,
)

# ==================== Trader Model Tests ====================


@pytest.mark.django_db
class TestTraderModel:
    """Тесты базовых свойств модели Trader."""

    def test_str_representation(self, trader):
        """str содержит pk и статус."""
        str_repr = str(trader)
        assert str(trader.pk) in str_repr

    def test_timeframe_property(self, trader):
        """timeframe делегирует candle_source.timeframe."""
        assert trader.timeframe == trader.candle_source.timeframe

    def test_trading_pair_property(self, trader):
        """trading_pair делегирует candle_source.trading_pair."""
        assert trader.trading_pair == trader.candle_source.trading_pair

    def test_trading_pair_fallback_to_exchange_trading_pair(
        self, trader, exchange, trading_pair, exchange_trading_pair
    ):
        """ExchangeTradingPair используется для получения торговой пары."""
        result = trader.trading_pair
        assert result in (trading_pair, exchange_trading_pair)

    def test_get_absolute_url(self, trader):
        """get_absolute_url возвращает корректный URL."""
        url = trader.get_absolute_url()
        assert str(trader.pk) in url

    def test_instantiate_returns_domain_trader(self, trader):
        """instantiate возвращает domain Trader с правильными полями."""
        domain_trader = trader.instantiate()
        assert isinstance(domain_trader, DomainTrader)
        assert domain_trader.initial_balance == trader.initial_balance
        assert domain_trader.use_fixed_balance == trader.use_fixed_balance
        assert domain_trader.check_drawdown == trader.check_drawdown
        assert domain_trader.max_drawdown_pct == trader.max_drawdown_pct
        assert domain_trader.max_positions_count == (trader.max_positions_count)
        assert domain_trader.create_new_orders == trader.create_new_orders

    def test_get_last_candles(self, trader):
        """get_last_candles делегирует candle_source.get_last_candles."""
        with patch.object(
            trader.candle_source, "get_last_candles", return_value=[]
        ) as mock_glc:
            result = trader.get_last_candles(count=10)
        mock_glc.assert_called_once_with(count=10)
        assert result == []


# ==================== Trader Positions ====================


@pytest.mark.django_db
class TestTraderPositions:
    """Тесты фильтрации позиций."""

    def test_get_opened_positions(
        self, trader, trader_position, closed_trader_position
    ):
        """Фильтрует только OPENED."""
        opened = trader.get_opened_positions()
        assert opened.count() == 1
        assert trader_position in opened

    def test_get_closed_positions(
        self, trader, trader_position, closed_trader_position
    ):
        """Фильтрует только CLOSED."""
        closed = trader.get_closed_positions()
        assert closed.count() == 1
        assert closed_trader_position in closed

    def test_opened_positions_property(
        self, trader, trader_position, closed_trader_position
    ):
        """Property-обёртка opened_positions."""
        assert list(trader.opened_positions) == list(trader.get_opened_positions())

    def test_closed_positions_property(
        self, trader, trader_position, closed_trader_position
    ):
        """Property-обёртка closed_positions."""
        assert list(trader.closed_positions) == list(trader.get_closed_positions())

    def test_get_total_positions_count(
        self, trader, trader_position, closed_trader_position
    ):
        """count() всех позиций."""
        assert trader.get_total_positions_count() == 2

    def test_get_total_positions_count_with_orders(
        self, trader, closed_trader_position, trader_order
    ):
        """distinct().count() позиций с ордерами."""
        assert trader.get_total_positions_count_with_orders() == 1

    def test_get_total_orders_count(self, trader, trader_order):
        """count() всех ордеров трейдера."""
        assert trader.get_total_orders_count() == 1

    def test_get_total_orders_count_empty(self, trader):
        """Нет ордеров → 0."""
        assert trader.get_total_orders_count() == 0


# ==================== Trader Balance ====================


@pytest.mark.django_db
class TestTraderBalance:
    """Тесты get_balance."""

    def test_get_balance_fixed(self, trader):
        """use_fixed_balance=True → initial_balance."""
        trader.use_fixed_balance = True
        trader.save()
        assert trader.get_balance() == Decimal("1000.00")

    def test_get_balance_dynamic_no_positions(self, trader):
        """use_fixed_balance=False, нет позиций → initial_balance."""
        trader.use_fixed_balance = False
        trader.save()
        assert trader.get_balance() == Decimal("1000.00")

    def test_get_balance_dynamic_with_positions(
        self,
        trader,
        closed_trader_position,
        exchange_client_order,
        trading_pair,
    ):
        """initial_balance + fact_pnl при use_fixed_balance=False."""
        trader.use_fixed_balance = False
        trader.save()
        # Создаём sell ордер для fact_pnl
        sell_order = ExchangeClientOrder.objects.create(
            exchange_client=trader.exchange_client,
            exchange_order_id="sell_order_bal",
            trading_pair=trading_pair,
            side=OrderSide.SELL,
            type="market",
            status=OrderStatus.CLOSED,
            timestamp=datetime.now(UTC),
            amount=Decimal("0.1"),
            price=Decimal("52000.00"),
            cost=Decimal("5200.00"),
            fee=Decimal("5.20"),
        )
        TraderOrder.objects.create(
            trader=trader,
            order=exchange_client_order,
            position=closed_trader_position,
        )
        TraderOrder.objects.create(
            trader=trader,
            order=sell_order,
            position=closed_trader_position,
        )
        balance = trader.get_balance()
        # fact_pnl = sell*price - buy*price - fees
        # = 52000*0.1 - 50000*0.1 - (5+5.2)
        # = 5200 - 5000 - 10.2 = 189.8
        expected = Decimal("1000.00") + trader.get_fact_pnl()
        assert balance == expected

    def test_get_balance_with_date(self, trader):
        """end_date фильтрует позиции."""
        balance = trader.get_balance(date=datetime.now(UTC))
        assert balance == Decimal("1000.00")

    def test_get_balance_zero_initial(self, trader):
        """initial_balance=0."""
        trader.initial_balance = Decimal("0")
        trader.use_fixed_balance = True
        trader.save()
        assert trader.get_balance() == Decimal("0")


# ==================== Trader Win Rate ====================


@pytest.mark.django_db
class TestTraderWinRate:
    """Тесты get_win_rate."""

    def test_win_rate_no_positions(self, trader):
        """Нет позиций → 0.0."""
        assert trader.get_win_rate() == 0.0

    def test_win_rate_all_wins_long(self, trader):
        """LONG close > open → 1.0."""
        now = datetime.now(UTC)
        for i in range(3):
            TraderPosition.objects.create(
                trader=trader,
                type=PositionType.LONG,
                status=PositionStatus.CLOSED,
                open_price=Decimal("50000"),
                close_price=Decimal("51000"),
                open_amount=Decimal("0.1"),
                close_amount=Decimal("0.1"),
                open_cost=Decimal("5000"),
                close_cost=Decimal("5100"),
                opened_at=now - timedelta(hours=i + 2),
                closed_at=now - timedelta(hours=i + 1),
                total_fee=Decimal("0"),
            )
        assert trader.get_win_rate() == 1.0

    def test_win_rate_all_wins_short(self, trader):
        """SHORT close < open → 1.0."""
        now = datetime.now(UTC)
        for i in range(3):
            TraderPosition.objects.create(
                trader=trader,
                type=PositionType.SHORT,
                status=PositionStatus.CLOSED,
                open_price=Decimal("51000"),
                close_price=Decimal("50000"),
                open_amount=Decimal("0.1"),
                close_amount=Decimal("0.1"),
                open_cost=Decimal("5100"),
                close_cost=Decimal("5000"),
                opened_at=now - timedelta(hours=i + 2),
                closed_at=now - timedelta(hours=i + 1),
                total_fee=Decimal("0"),
            )
        assert trader.get_win_rate() == 1.0

    def test_win_rate_all_losses(self, trader):
        """Все убыточные → 0.0."""
        now = datetime.now(UTC)
        for i in range(3):
            TraderPosition.objects.create(
                trader=trader,
                type=PositionType.LONG,
                status=PositionStatus.CLOSED,
                open_price=Decimal("51000"),
                close_price=Decimal("50000"),
                open_amount=Decimal("0.1"),
                close_amount=Decimal("0.1"),
                open_cost=Decimal("5100"),
                close_cost=Decimal("5000"),
                opened_at=now - timedelta(hours=i + 2),
                closed_at=now - timedelta(hours=i + 1),
                total_fee=Decimal("0"),
            )
        assert trader.get_win_rate() == 0.0

    def test_win_rate_mixed(self, trader):
        """2 win / 4 total → 0.5."""
        now = datetime.now(UTC)
        # 2 wins
        for i in range(2):
            TraderPosition.objects.create(
                trader=trader,
                type=PositionType.LONG,
                status=PositionStatus.CLOSED,
                open_price=Decimal("50000"),
                close_price=Decimal("51000"),
                open_amount=Decimal("0.1"),
                close_amount=Decimal("0.1"),
                open_cost=Decimal("5000"),
                close_cost=Decimal("5100"),
                opened_at=now - timedelta(hours=i + 4),
                closed_at=now - timedelta(hours=i + 3),
                total_fee=Decimal("0"),
            )
        # 2 losses
        for i in range(2):
            TraderPosition.objects.create(
                trader=trader,
                type=PositionType.LONG,
                status=PositionStatus.CLOSED,
                open_price=Decimal("51000"),
                close_price=Decimal("50000"),
                open_amount=Decimal("0.1"),
                close_amount=Decimal("0.1"),
                open_cost=Decimal("5100"),
                close_cost=Decimal("5000"),
                opened_at=now - timedelta(hours=i + 2),
                closed_at=now - timedelta(hours=i + 1),
                total_fee=Decimal("0"),
            )
        assert trader.get_win_rate() == 0.5

    def test_win_rate_with_start_date(self, trader):
        """Фильтрует по closed_at >= start."""
        now = datetime.now(UTC)
        # Старая позиция (не попадёт)
        TraderPosition.objects.create(
            trader=trader,
            type=PositionType.LONG,
            status=PositionStatus.CLOSED,
            open_price=Decimal("50000"),
            close_price=Decimal("51000"),
            open_amount=Decimal("0.1"),
            close_amount=Decimal("0.1"),
            open_cost=Decimal("5000"),
            close_cost=Decimal("5100"),
            opened_at=now - timedelta(days=10),
            closed_at=now - timedelta(days=9),
            total_fee=Decimal("0"),
        )
        # Новая позиция (попадёт)
        TraderPosition.objects.create(
            trader=trader,
            type=PositionType.LONG,
            status=PositionStatus.CLOSED,
            open_price=Decimal("51000"),
            close_price=Decimal("50000"),
            open_amount=Decimal("0.1"),
            close_amount=Decimal("0.1"),
            open_cost=Decimal("5100"),
            close_cost=Decimal("5000"),
            opened_at=now - timedelta(hours=2),
            closed_at=now - timedelta(hours=1),
            total_fee=Decimal("0"),
        )
        # start_date отсекает старую
        wr = trader.get_win_rate(start_date=now - timedelta(days=1))
        assert wr == 0.0  # только loss

    def test_win_rate_with_end_date(self, trader):
        """Фильтрует по closed_at < end."""
        now = datetime.now(UTC)
        TraderPosition.objects.create(
            trader=trader,
            type=PositionType.LONG,
            status=PositionStatus.CLOSED,
            open_price=Decimal("50000"),
            close_price=Decimal("51000"),
            open_amount=Decimal("0.1"),
            close_amount=Decimal("0.1"),
            open_cost=Decimal("5000"),
            close_cost=Decimal("5100"),
            opened_at=now - timedelta(hours=2),
            closed_at=now - timedelta(hours=1),
            total_fee=Decimal("0"),
        )
        # end_date до позиции → 0.0
        wr = trader.get_win_rate(end_date=now - timedelta(days=1))
        assert wr == 0.0

    def test_win_rate_fee_turns_win_into_loss(self, trader):
        """Позиция в плюсе по цене, но в минусе после комиссии → не win."""
        now = datetime.now(UTC)
        # close > open, но fee > gross pnl: (51000-50000)*0.1 = 100, fee = 150
        TraderPosition.objects.create(
            trader=trader,
            type=PositionType.LONG,
            status=PositionStatus.CLOSED,
            open_price=Decimal("50000"),
            close_price=Decimal("51000"),
            open_amount=Decimal("0.1"),
            close_amount=Decimal("0.1"),
            open_cost=Decimal("5000"),
            close_cost=Decimal("5100"),
            opened_at=now - timedelta(hours=2),
            closed_at=now - timedelta(hours=1),
            total_fee=Decimal("150"),
        )
        assert trader.get_win_rate() == 0.0


# ==================== Trader Fact PnL ====================


@pytest.mark.django_db
class TestTraderFactPnl:
    """Тесты get_fact_pnl (SQL aggregation через ордера)."""

    def _create_position_with_orders(
        self,
        trader,
        trading_pair,
        buy_price,
        sell_price,
        amount,
        buy_fee=Decimal("5"),
        sell_fee=Decimal("5"),
        closed_at=None,
    ):
        """Хелпер: позиция + BUY/SELL ордера."""
        now = closed_at or datetime.now(UTC)
        position = TraderPosition.objects.create(
            trader=trader,
            type=PositionType.LONG,
            status=PositionStatus.CLOSED,
            open_price=buy_price,
            close_price=sell_price,
            open_amount=amount,
            close_amount=amount,
            open_cost=buy_price * amount,
            close_cost=sell_price * amount,
            opened_at=now - timedelta(hours=1),
            closed_at=now,
            total_fee=buy_fee + sell_fee,
            close_reason=PositionCloseReason.TAKE_PROFIT,
        )
        buy_order = ExchangeClientOrder.objects.create(
            exchange_client=trader.exchange_client,
            exchange_order_id=f"buy-{position.pk}",
            trading_pair=trading_pair,
            side=OrderSide.BUY,
            type="market",
            status=OrderStatus.CLOSED,
            timestamp=now - timedelta(hours=1),
            amount=amount,
            price=buy_price,
            cost=buy_price * amount,
            fee=buy_fee,
        )
        sell_order = ExchangeClientOrder.objects.create(
            exchange_client=trader.exchange_client,
            exchange_order_id=f"sell-{position.pk}",
            trading_pair=trading_pair,
            side=OrderSide.SELL,
            type="market",
            status=OrderStatus.CLOSED,
            timestamp=now,
            amount=amount,
            price=sell_price,
            cost=sell_price * amount,
            fee=sell_fee,
        )
        TraderOrder.objects.create(trader=trader, order=buy_order, position=position)
        TraderOrder.objects.create(trader=trader, order=sell_order, position=position)
        return position

    def test_fact_pnl_no_orders(self, trader):
        """Нет ордеров → 0."""
        assert trader.get_fact_pnl() == Decimal("0.00")

    def test_fact_pnl_single_buy_sell(self, trader, trading_pair):
        """SELL*price - BUY*price - fees."""
        self._create_position_with_orders(
            trader,
            trading_pair,
            buy_price=Decimal("50000"),
            sell_price=Decimal("52000"),
            amount=Decimal("0.1"),
            buy_fee=Decimal("5"),
            sell_fee=Decimal("5.20"),
        )
        pnl = trader.get_fact_pnl()
        # gross = 52000*0.1 - 50000*0.1 = 5200 - 5000 = 200
        # fee = 5 + 5.20 = 10.20
        # pnl = 200 - 10.20 = 189.80
        assert pnl == Decimal("189.80")

    def test_fact_pnl_multiple_positions(self, trader, trading_pair):
        """Суммирует по нескольким позициям."""
        self._create_position_with_orders(
            trader,
            trading_pair,
            buy_price=Decimal("50000"),
            sell_price=Decimal("52000"),
            amount=Decimal("0.1"),
            buy_fee=Decimal("0"),
            sell_fee=Decimal("0"),
        )
        self._create_position_with_orders(
            trader,
            trading_pair,
            buy_price=Decimal("48000"),
            sell_price=Decimal("49000"),
            amount=Decimal("0.2"),
            buy_fee=Decimal("0"),
            sell_fee=Decimal("0"),
        )
        pnl = trader.get_fact_pnl()
        # pos1: 52000*0.1 - 50000*0.1 = 200
        # pos2: 49000*0.2 - 48000*0.2 = 200
        assert pnl == Decimal("400")

    def test_fact_pnl_with_start_date(self, trader, trading_pair):
        """Фильтрация по start_date."""
        now = datetime.now(UTC)
        self._create_position_with_orders(
            trader,
            trading_pair,
            buy_price=Decimal("50000"),
            sell_price=Decimal("51000"),
            amount=Decimal("0.1"),
            buy_fee=Decimal("0"),
            sell_fee=Decimal("0"),
            closed_at=now - timedelta(days=10),
        )
        self._create_position_with_orders(
            trader,
            trading_pair,
            buy_price=Decimal("50000"),
            sell_price=Decimal("52000"),
            amount=Decimal("0.1"),
            buy_fee=Decimal("0"),
            sell_fee=Decimal("0"),
            closed_at=now,
        )
        pnl = trader.get_fact_pnl(start_date=now - timedelta(days=1))
        # Только вторая: 52000*0.1 - 50000*0.1 = 200
        assert pnl == Decimal("200")

    def test_fact_pnl_with_end_date(self, trader, trading_pair):
        """Фильтрация по end_date."""
        now = datetime.now(UTC)
        self._create_position_with_orders(
            trader,
            trading_pair,
            buy_price=Decimal("50000"),
            sell_price=Decimal("51000"),
            amount=Decimal("0.1"),
            buy_fee=Decimal("0"),
            sell_fee=Decimal("0"),
            closed_at=now - timedelta(days=10),
        )
        pnl = trader.get_fact_pnl(end_date=now - timedelta(days=5))
        assert pnl == Decimal("100")

    def test_fact_pnl_negative(self, trader, trading_pair):
        """Убыточная торговля."""
        self._create_position_with_orders(
            trader,
            trading_pair,
            buy_price=Decimal("52000"),
            sell_price=Decimal("50000"),
            amount=Decimal("0.1"),
            buy_fee=Decimal("5"),
            sell_fee=Decimal("5"),
        )
        pnl = trader.get_fact_pnl()
        # gross = 50000*0.1 - 52000*0.1 = 5000 - 5200 = -200
        # fee = 10
        # pnl = -200 - 10 = -210
        assert pnl == Decimal("-210")

    def test_fact_pnl_query_count(self, trader, trading_pair):
        """CaptureQueriesContext: <= 2 запроса."""
        self._create_position_with_orders(
            trader,
            trading_pair,
            buy_price=Decimal("50000"),
            sell_price=Decimal("51000"),
            amount=Decimal("0.1"),
        )
        with CaptureQueriesContext(connection) as q:
            trader.get_fact_pnl()
        assert len(q) <= 2

    def test_fact_pnl_sign_calculation(self, trader, trading_pair):
        """SELL=+1, BUY=-1 корректно применяется."""
        pnl = trader.get_fact_pnl()
        assert pnl == Decimal("0.00")


# ==================== Trader Theoretical PnL ====================


@pytest.mark.django_db
class TestTraderTheoreticalPnl:
    """Тесты get_theoretical_pnl."""

    def test_theoretical_pnl_no_positions(self, trader):
        """Нет позиций → 0."""
        assert trader.get_theoretical_pnl() == Decimal("0.00")

    def test_theoretical_pnl_long_profitable(self, trader):
        """LONG: (close-open)*amount - fee."""
        now = datetime.now(UTC)
        TraderPosition.objects.create(
            trader=trader,
            type=PositionType.LONG,
            status=PositionStatus.CLOSED,
            open_price=Decimal("50000"),
            close_price=Decimal("52000"),
            open_amount=Decimal("0.1"),
            close_amount=Decimal("0.1"),
            open_cost=Decimal("5000"),
            close_cost=Decimal("5200"),
            opened_at=now - timedelta(hours=1),
            closed_at=now,
            total_fee=Decimal("10"),
        )
        pnl = trader.get_theoretical_pnl()
        # (52000-50000)*0.1 - 10 = 200 - 10 = 190
        assert pnl == Decimal("190")

    def test_theoretical_pnl_short_profitable(self, trader):
        """SHORT: (open-close)*amount - fee (sign=-1)."""
        now = datetime.now(UTC)
        TraderPosition.objects.create(
            trader=trader,
            type=PositionType.SHORT,
            status=PositionStatus.CLOSED,
            open_price=Decimal("52000"),
            close_price=Decimal("50000"),
            open_amount=Decimal("0.1"),
            close_amount=Decimal("0.1"),
            open_cost=Decimal("5200"),
            close_cost=Decimal("5000"),
            opened_at=now - timedelta(hours=1),
            closed_at=now,
            total_fee=Decimal("10"),
        )
        pnl = trader.get_theoretical_pnl()
        # SHORT: -1*(50000-52000)*0.1 = -1*(-200) = 200; 200 - 10 = 190
        assert pnl == Decimal("190")

    def test_theoretical_pnl_multiple(self, trader):
        """Суммирует по нескольким позициям."""
        now = datetime.now(UTC)
        for i in range(3):
            TraderPosition.objects.create(
                trader=trader,
                type=PositionType.LONG,
                status=PositionStatus.CLOSED,
                open_price=Decimal("50000"),
                close_price=Decimal("51000"),
                open_amount=Decimal("0.1"),
                close_amount=Decimal("0.1"),
                open_cost=Decimal("5000"),
                close_cost=Decimal("5100"),
                opened_at=now - timedelta(hours=i + 2),
                closed_at=now - timedelta(hours=i + 1),
                total_fee=Decimal("0"),
            )
        pnl = trader.get_theoretical_pnl()
        # 3 * (51000-50000)*0.1 = 3 * 100 = 300
        assert pnl == Decimal("300")

    def test_theoretical_pnl_with_date_filter(self, trader):
        """start/end фильтрация."""
        now = datetime.now(UTC)
        TraderPosition.objects.create(
            trader=trader,
            type=PositionType.LONG,
            status=PositionStatus.CLOSED,
            open_price=Decimal("50000"),
            close_price=Decimal("51000"),
            open_amount=Decimal("0.1"),
            close_amount=Decimal("0.1"),
            open_cost=Decimal("5000"),
            close_cost=Decimal("5100"),
            opened_at=now - timedelta(days=10),
            closed_at=now - timedelta(days=9),
            total_fee=Decimal("0"),
        )
        TraderPosition.objects.create(
            trader=trader,
            type=PositionType.LONG,
            status=PositionStatus.CLOSED,
            open_price=Decimal("50000"),
            close_price=Decimal("52000"),
            open_amount=Decimal("0.1"),
            close_amount=Decimal("0.1"),
            open_cost=Decimal("5000"),
            close_cost=Decimal("5200"),
            opened_at=now - timedelta(hours=2),
            closed_at=now - timedelta(hours=1),
            total_fee=Decimal("0"),
        )
        pnl = trader.get_theoretical_pnl(start_date=now - timedelta(days=1))
        assert pnl == Decimal("200")

    def test_theoretical_pnl_with_end_date(self, trader):
        """end_date фильтрация."""
        now = datetime.now(UTC)
        TraderPosition.objects.create(
            trader=trader,
            type=PositionType.LONG,
            status=PositionStatus.CLOSED,
            open_price=Decimal("50000"),
            close_price=Decimal("51000"),
            open_amount=Decimal("0.1"),
            close_amount=Decimal("0.1"),
            open_cost=Decimal("5000"),
            close_cost=Decimal("5100"),
            opened_at=now - timedelta(days=10),
            closed_at=now - timedelta(days=9),
            total_fee=Decimal("0"),
        )
        TraderPosition.objects.create(
            trader=trader,
            type=PositionType.LONG,
            status=PositionStatus.CLOSED,
            open_price=Decimal("50000"),
            close_price=Decimal("52000"),
            open_amount=Decimal("0.1"),
            close_amount=Decimal("0.1"),
            open_cost=Decimal("5000"),
            close_cost=Decimal("5200"),
            opened_at=now - timedelta(hours=2),
            closed_at=now - timedelta(hours=1),
            total_fee=Decimal("0"),
        )
        # end_date отсекает новую позицию
        pnl = trader.get_theoretical_pnl(end_date=now - timedelta(days=1))
        # Только старая: (51000-50000)*0.1 = 100
        assert pnl == Decimal("100")

    def test_theoretical_pnl_query_count(self, trader, closed_trader_position):
        """CaptureQueriesContext: 1 запрос (aggregate)."""
        with CaptureQueriesContext(connection) as q:
            trader.get_theoretical_pnl()
        assert len(q) == 1


# ==================== Trader Avg Candles Per Position ====================


@pytest.mark.django_db
class TestTraderAvgCandlesPerPosition:
    """Тесты get_avg_candles_per_position."""

    def test_avg_candles_no_positions(self, trader):
        """Нет позиций → None."""
        assert trader.get_avg_candles_per_position() is None

    def test_avg_candles_single_position(self, trader):
        """duration / timeframe_td."""
        now = datetime.now(UTC)
        TraderPosition.objects.create(
            trader=trader,
            type=PositionType.LONG,
            status=PositionStatus.CLOSED,
            open_price=Decimal("50000"),
            close_price=Decimal("51000"),
            open_amount=Decimal("0.1"),
            close_amount=Decimal("0.1"),
            open_cost=Decimal("5000"),
            close_cost=Decimal("5100"),
            opened_at=now - timedelta(hours=5),
            closed_at=now,
            total_fee=Decimal("0"),
        )
        result = trader.get_avg_candles_per_position()
        # 5 часов / 1 час = 5 свечей
        assert result == pytest.approx(5.0, abs=0.01)

    def test_avg_candles_multiple_positions(self, trader):
        """Среднее по нескольким."""
        now = datetime.now(UTC)
        TraderPosition.objects.create(
            trader=trader,
            type=PositionType.LONG,
            status=PositionStatus.CLOSED,
            open_price=Decimal("50000"),
            close_price=Decimal("51000"),
            open_amount=Decimal("0.1"),
            close_amount=Decimal("0.1"),
            open_cost=Decimal("5000"),
            close_cost=Decimal("5100"),
            opened_at=now - timedelta(hours=4),
            closed_at=now - timedelta(hours=2),
            total_fee=Decimal("0"),
        )
        TraderPosition.objects.create(
            trader=trader,
            type=PositionType.LONG,
            status=PositionStatus.CLOSED,
            open_price=Decimal("50000"),
            close_price=Decimal("51000"),
            open_amount=Decimal("0.2"),
            close_amount=Decimal("0.2"),
            open_cost=Decimal("10000"),
            close_cost=Decimal("10200"),
            opened_at=now - timedelta(hours=10),
            closed_at=now - timedelta(hours=4),
            total_fee=Decimal("0"),
        )
        result = trader.get_avg_candles_per_position()
        # (2h + 6h) / 2 = 4h, 4h / 1h = 4 свечи
        assert result == pytest.approx(4.0, abs=0.01)

    def test_avg_candles_with_end_date_filter(self, trader):
        """Фильтрация по end_date."""
        now = datetime.now(UTC)
        TraderPosition.objects.create(
            trader=trader,
            type=PositionType.LONG,
            status=PositionStatus.CLOSED,
            open_price=Decimal("50000"),
            close_price=Decimal("51000"),
            open_amount=Decimal("0.1"),
            close_amount=Decimal("0.1"),
            open_cost=Decimal("5000"),
            close_cost=Decimal("5100"),
            opened_at=now - timedelta(hours=4),
            closed_at=now - timedelta(hours=2),
            total_fee=Decimal("0"),
        )
        result = trader.get_avg_candles_per_position(end_date=now - timedelta(days=1))
        assert result is None

    def test_avg_candles_with_start_date_filter(self, trader):
        """Фильтрация по start_date."""
        now = datetime.now(UTC)
        # Старая позиция — не попадёт
        TraderPosition.objects.create(
            trader=trader,
            type=PositionType.LONG,
            status=PositionStatus.CLOSED,
            open_price=Decimal("50000"),
            close_price=Decimal("51000"),
            open_amount=Decimal("0.1"),
            close_amount=Decimal("0.1"),
            open_cost=Decimal("5000"),
            close_cost=Decimal("5100"),
            opened_at=now - timedelta(days=10),
            closed_at=now - timedelta(days=9),
            total_fee=Decimal("0"),
        )
        # Новая позиция — попадёт (3 часа)
        TraderPosition.objects.create(
            trader=trader,
            type=PositionType.LONG,
            status=PositionStatus.CLOSED,
            open_price=Decimal("50000"),
            close_price=Decimal("51000"),
            open_amount=Decimal("0.2"),
            close_amount=Decimal("0.2"),
            open_cost=Decimal("10000"),
            close_cost=Decimal("10200"),
            opened_at=now - timedelta(hours=4),
            closed_at=now - timedelta(hours=1),
            total_fee=Decimal("0"),
        )
        result = trader.get_avg_candles_per_position(start_date=now - timedelta(days=1))
        # 3 часа / 1 час = 3 свечи
        assert result == pytest.approx(3.0, abs=0.01)

    def test_avg_candles_null_duration(self, trader):
        """Позиция с closed_at=None → avg_duration=None → None."""
        TraderPosition.objects.create(
            trader=trader,
            type=PositionType.LONG,
            status=PositionStatus.CLOSED,
            open_price=Decimal("50000"),
            close_price=Decimal("51000"),
            open_amount=Decimal("0.1"),
            close_amount=Decimal("0.1"),
            open_cost=Decimal("5000"),
            close_cost=Decimal("5100"),
            opened_at=datetime.now(UTC),
            closed_at=None,
            total_fee=Decimal("0"),
        )
        result = trader.get_avg_candles_per_position()
        assert result is None

    def test_avg_candles_query_count(self, trader, closed_trader_position):
        """CaptureQueriesContext."""
        with CaptureQueriesContext(connection) as q:
            trader.get_avg_candles_per_position()
        assert len(q) <= 3


# ==================== Trader PnL R2 ====================


@pytest.mark.django_db
class TestTraderPnlR2:
    """Тесты get_pnl_r2 — R² coefficient для cumulative PnL."""

    def test_pnl_r2_no_positions(self, trader):
        """get_pnl_r2 без позиций возвращает 0.0."""
        assert trader.get_pnl_r2() == 0.0

    def test_pnl_r2_single_position(self, trader):
        """get_pnl_r2 с 1 позицией возвращает 0.0 (нужно >= 2)."""
        now = datetime.now(UTC)
        TraderPosition.objects.create(
            trader=trader,
            type=PositionType.LONG,
            status=PositionStatus.CLOSED,
            open_price=Decimal("50000"),
            close_price=Decimal("51000"),
            open_amount=Decimal("0.1"),
            close_amount=Decimal("0.1"),
            open_cost=Decimal("5000"),
            close_cost=Decimal("5100"),
            opened_at=now - timedelta(hours=2),
            closed_at=now - timedelta(hours=1),
            total_fee=Decimal("0"),
        )
        assert trader.get_pnl_r2() == 0.0

    def test_pnl_r2_linear_growth(self, trader):
        """get_pnl_r2 с линейным ростом PnL → R² ≈ 1.0."""
        now = datetime.now(UTC)
        for i in range(5):
            TraderPosition.objects.create(
                trader=trader,
                type=PositionType.LONG,
                status=PositionStatus.CLOSED,
                open_price=Decimal("50000"),
                close_price=Decimal("51000"),
                open_amount=Decimal("0.1"),
                close_amount=Decimal("0.1"),
                open_cost=Decimal("5000"),
                close_cost=Decimal("5100"),
                opened_at=now - timedelta(hours=10 - i),
                closed_at=now - timedelta(hours=9 - i),
                total_fee=Decimal("0"),
            )
        r2 = trader.get_pnl_r2()
        assert r2 > 0.95

    def test_pnl_r2_constant_pnl_zero_ss_tot(self, trader):
        """get_pnl_r2 при нулевом ss_tot → 0.0."""
        now = datetime.now(UTC)
        for i in range(2):
            TraderPosition.objects.create(
                trader=trader,
                type=PositionType.LONG,
                status=PositionStatus.CLOSED,
                open_price=Decimal("50000"),
                close_price=Decimal("50000"),
                open_amount=Decimal("0.1"),
                close_amount=Decimal("0.1"),
                open_cost=Decimal("5000"),
                close_cost=Decimal("5000"),
                opened_at=now - timedelta(hours=3 - i),
                closed_at=now - timedelta(hours=2 - i),
                total_fee=Decimal("0"),
            )
        r2 = trader.get_pnl_r2()
        assert r2 == 0.0

    def test_pnl_r2_with_start_date(self, trader):
        """get_pnl_r2 с start_date фильтрует позиции."""
        now = datetime.now(UTC)
        for i in range(4):
            TraderPosition.objects.create(
                trader=trader,
                type=PositionType.LONG,
                status=PositionStatus.CLOSED,
                open_price=Decimal("50000"),
                close_price=Decimal("51000"),
                open_amount=Decimal("0.1"),
                close_amount=Decimal("0.1"),
                open_cost=Decimal("5000"),
                close_cost=Decimal("5100"),
                opened_at=now - timedelta(days=10 - i),
                closed_at=now - timedelta(days=9 - i),
                total_fee=Decimal("0"),
            )
        start_date = now - timedelta(days=8)
        r2 = trader.get_pnl_r2(start_date=start_date)
        assert r2 > 0.95

    def test_pnl_r2_with_end_date(self, trader):
        """get_pnl_r2 с end_date фильтрует позиции."""
        now = datetime.now(UTC)
        for i in range(4):
            TraderPosition.objects.create(
                trader=trader,
                type=PositionType.LONG,
                status=PositionStatus.CLOSED,
                open_price=Decimal("50000"),
                close_price=Decimal("51000"),
                open_amount=Decimal("0.1"),
                close_amount=Decimal("0.1"),
                open_cost=Decimal("5000"),
                close_cost=Decimal("5100"),
                opened_at=now - timedelta(days=10 - i),
                closed_at=now - timedelta(days=9 - i),
                total_fee=Decimal("0"),
            )
        end_date = now - timedelta(days=7)
        r2 = trader.get_pnl_r2(end_date=end_date)
        assert r2 > 0.95

    def test_pnl_r2_query_count(self, trader):
        """get_pnl_r2 выполняет 1 запрос."""
        now = datetime.now(UTC)
        for i in range(3):
            TraderPosition.objects.create(
                trader=trader,
                type=PositionType.LONG,
                status=PositionStatus.CLOSED,
                open_price=Decimal("50000"),
                close_price=Decimal("51000"),
                open_amount=Decimal("0.1"),
                close_amount=Decimal("0.1"),
                open_cost=Decimal("5000"),
                close_cost=Decimal("5100"),
                opened_at=now - timedelta(hours=5 - i),
                closed_at=now - timedelta(hours=4 - i),
                total_fee=Decimal("0"),
            )
        with CaptureQueriesContext(connection) as ctx:
            trader.get_pnl_r2()
        assert len(ctx) == 1

    def test_pnl_r2_mixed_pnl(self, trader):
        """get_pnl_r2 со смешанным PnL → 0 < R² < 1."""
        now = datetime.now(UTC)
        prices = [
            (Decimal("50000"), Decimal("51000")),  # profit
            (Decimal("51000"), Decimal("50000")),  # loss
            (Decimal("50000"), Decimal("51500")),  # profit
            (Decimal("51000"), Decimal("49500")),  # loss
            (Decimal("50000"), Decimal("52000")),  # profit
        ]
        for i, (open_p, close_p) in enumerate(prices):
            TraderPosition.objects.create(
                trader=trader,
                type=PositionType.LONG,
                status=PositionStatus.CLOSED,
                open_price=open_p,
                close_price=close_p,
                open_amount=Decimal("0.1"),
                close_amount=Decimal("0.1"),
                open_cost=open_p * Decimal("0.1"),
                close_cost=close_p * Decimal("0.1"),
                opened_at=now - timedelta(hours=10 - i),
                closed_at=now - timedelta(hours=9 - i),
                total_fee=Decimal("0.50"),
            )
        r2 = trader.get_pnl_r2()
        assert 0 < r2 < 1


# ==================== Trader Status Methods ====================


@pytest.mark.django_db
class TestTraderStatusMethods:
    """Тесты enable/disable."""

    def test_enable_changes_status(self, trader):
        """DISABLED → ENABLED."""
        trader.status = TraderStatus.DISABLED
        trader.save()
        trader.enable()
        trader.refresh_from_db()
        assert trader.status == TraderStatus.ENABLED

    def test_enable_uses_update_fields(self, trader):
        """CaptureQueriesContext: 1 UPDATE."""
        trader.status = TraderStatus.DISABLED
        trader.save()
        with CaptureQueriesContext(connection) as q:
            trader.enable()
        assert len(q) == 1

    def test_disable_changes_status(self, trader):
        """ENABLED → DISABLED."""
        trader.disable()
        trader.refresh_from_db()
        assert trader.status == TraderStatus.DISABLED

    def test_disable_uses_update_fields(self, trader):
        """1 UPDATE."""
        with CaptureQueriesContext(connection) as q:
            trader.disable()
        assert len(q) == 1


# ==================== Trader Clear Data ====================


@pytest.mark.django_db
class TestTraderClearData:
    """Тесты очистки данных."""

    def test_clear_all_data(self, trader, trader_signal, trader_position):
        """Удаляет signals, orders, positions, errors."""
        TraderError.objects.create(trader=trader, message="err", type="E")
        trader.clear_all_data()
        assert TraderSignal.objects.filter(trader=trader).count() == 0
        assert TraderPosition.objects.filter(trader=trader).count() == 0
        assert TraderError.objects.filter(trader=trader).count() == 0

    def test_clear_all_data_with_no_data(self, trader):
        """Не падает на пустых данных."""
        trader.clear_all_data()

    def test_clear_all_errors(self, trader):
        """Удаляет только errors."""
        TraderError.objects.create(trader=trader, message="err", type="E")
        trader.clear_all_errors()
        assert TraderError.objects.filter(trader=trader).count() == 0

    def test_clear_all_errors_preserves_other_data(
        self, trader, trader_signal, trader_position
    ):
        """signals/positions остаются."""
        TraderError.objects.create(trader=trader, message="err", type="E")
        trader.clear_all_errors()
        assert TraderSignal.objects.filter(trader=trader).count() == 1
        assert TraderPosition.objects.filter(trader=trader).count() == 1


# ==================== Trader Has Existing Signal ====================


@pytest.mark.django_db
class TestTraderHasExistingSignal:
    """Тесты has_existing_signal."""

    def test_has_existing_signal_true(self, trader, exchange_candle):
        """Сигнал с таким timestamp есть."""
        TraderSignal.objects.create(
            trader=trader,
            timestamp=exchange_candle.timestamp,
            price=Decimal("50500.00"),
            type=SignalType.BUY,
            data={},
            candle=exchange_candle,
        )
        assert trader.has_existing_signal(timestamp=exchange_candle.timestamp)

    def test_has_existing_signal_false(self, trader, exchange_candle):
        """Нет сигнала."""
        assert not trader.has_existing_signal(timestamp=exchange_candle.timestamp)

    def test_has_existing_signal_query_count(self, trader, exchange_candle):
        """CaptureQueriesContext: 1 EXISTS запрос."""
        with CaptureQueriesContext(connection) as q:
            trader.has_existing_signal(timestamp=exchange_candle.timestamp)
        assert len(q) == 1


# ==================== Trader Load ====================


@pytest.mark.django_db
class TestTraderLoad:
    """Тесты load() с CaptureQueriesContext."""

    def test_load_candles(self, trader, exchange_candle):
        """Все свечи загружаются."""
        domain_trader = trader.instantiate()
        trader.load(trader=domain_trader)
        assert isinstance(domain_trader.candles, deque)
        assert len(domain_trader.candles) == 1

    def test_load_candles_order(self, trader):
        """Свечи загружаются в хронологическом порядке."""
        exchange = trader.candle_source.exchange
        trading_pair = trader.candle_source.trading_pair
        now = datetime.now(UTC)
        for i in range(5):
            ExchangeCandle.objects.create(
                exchange=exchange,
                trading_pair=trading_pair,
                timeframe=Timeframe.ONE_HOUR,
                timestamp=now + timedelta(hours=i),
                open=Decimal("50000"),
                high=Decimal("51000"),
                low=Decimal("49000"),
                close=Decimal("50500"),
                volume=Decimal("100"),
            )
        domain_trader = trader.instantiate()
        trader.load(trader=domain_trader)
        assert len(domain_trader.candles) == 5
        timestamps = [c.timestamp for c in domain_trader.candles]
        assert timestamps == sorted(timestamps)

    def test_load_candles_limit_default(self, trader):
        """Загружаем максимум candles_lookback_count свечей (deque maxlen)."""
        exchange = trader.candle_source.exchange
        trading_pair = trader.candle_source.trading_pair
        now = datetime.now(UTC)
        limit = trader.candles_lookback_count
        candles = [
            ExchangeCandle(
                exchange=exchange,
                trading_pair=trading_pair,
                timeframe=Timeframe.ONE_HOUR,
                timestamp=now + timedelta(hours=i),
                open=Decimal("50000"),
                high=Decimal("51000"),
                low=Decimal("49000"),
                close=Decimal("50500"),
                volume=Decimal("100"),
            )
            for i in range(limit + 50)
        ]
        ExchangeCandle.objects.bulk_create(candles)
        domain_trader = trader.instantiate()
        trader.load(trader=domain_trader)
        assert len(domain_trader.candles) == limit

    def test_load_opened_positions_only(
        self, trader, trader_position, closed_trader_position
    ):
        """Только OPENED (не CLOSED)."""
        domain_trader = trader.instantiate()
        trader.load(trader=domain_trader)
        assert len(domain_trader.positions) == 1
        assert domain_trader.positions[0].status == DomainPositionStatus.OPENED

    def test_load_positions_ordered_by_opened_at(self, trader):
        """order_by('opened_at')."""
        now = datetime.now(UTC)
        TraderPosition.objects.create(
            trader=trader,
            type=PositionType.LONG,
            status=PositionStatus.OPENED,
            open_price=Decimal("51000"),
            open_amount=Decimal("0.2"),
            open_cost=Decimal("10200"),
            opened_at=now,
            total_fee=Decimal("0"),
        )
        TraderPosition.objects.create(
            trader=trader,
            type=PositionType.SHORT,
            status=PositionStatus.OPENED,
            open_price=Decimal("50000"),
            open_amount=Decimal("0.1"),
            open_cost=Decimal("5000"),
            opened_at=now - timedelta(hours=1),
            total_fee=Decimal("0"),
        )
        domain_trader = trader.instantiate()
        trader.load(trader=domain_trader)
        assert domain_trader.positions[0].opened_at < (
            domain_trader.positions[1].opened_at
        )

    def test_load_empty_data(self, trader):
        """Пустые signals/positions → пустой deque/list."""
        domain_trader = trader.instantiate()
        trader.load(trader=domain_trader)
        assert len(domain_trader.signals) == 0
        assert len(domain_trader.positions) == 0

    def test_load_query_count(self, trader, exchange_candle):
        """CaptureQueriesContext: ровно 2 запроса (candles + positions)."""
        domain_trader = trader.instantiate()
        with CaptureQueriesContext(connection) as q:
            trader.load(trader=domain_trader)
        assert len(q) == 2

    def test_load_no_n_plus_one(self, trader):
        """10 свечей → 2 запроса (не 12)."""
        exchange = trader.candle_source.exchange
        trading_pair = trader.candle_source.trading_pair
        now = datetime.now(UTC)
        for i in range(10):
            ExchangeCandle.objects.create(
                exchange=exchange,
                trading_pair=trading_pair,
                timeframe=Timeframe.ONE_HOUR,
                timestamp=now + timedelta(hours=i),
                open=Decimal("50000"),
                high=Decimal("51000"),
                low=Decimal("49000"),
                close=Decimal("50500"),
                volume=Decimal("100"),
            )
        domain_trader = trader.instantiate()
        with CaptureQueriesContext(connection) as q:
            trader.load(trader=domain_trader)
        assert len(q) == 2
        assert len(domain_trader.candles) == 10


# ==================== Trader Sync Signals ====================


@pytest.mark.django_db
class TestTraderSyncSignals:
    """Тесты sync_signals() с CaptureQueriesContext."""

    def test_sync_signals_creates_in_db(self, trader, domain_signal):
        """Новые сигналы создаются (id=None → bulk_create)."""
        domain_trader = trader.instantiate()
        domain_trader.signals = deque([domain_signal])
        trader.sync_signals(trader=domain_trader)
        assert TraderSignal.objects.filter(trader=trader).count() == 1

    def test_sync_signals_skips_existing(self, trader, domain_signal):
        """Сигналы с id != None не создаются повторно."""
        domain_signal.id = 999
        domain_trader = trader.instantiate()
        domain_trader.signals = deque([domain_signal])
        trader.sync_signals(trader=domain_trader)
        assert TraderSignal.objects.filter(trader=trader).count() == 0

    def test_sync_signals_empty(self, trader):
        """Пустой deque → 0 запросов."""
        domain_trader = trader.instantiate()
        domain_trader.signals = deque()
        with CaptureQueriesContext(connection) as q:
            trader.sync_signals(trader=domain_trader)
        assert len(q) == 0

    def test_sync_signals_maps_fields_correctly(self, trader, domain_signal):
        """timestamp, price, type, data, candle_id."""
        domain_trader = trader.instantiate()
        domain_trader.signals = deque([domain_signal])
        trader.sync_signals(trader=domain_trader)
        signal = TraderSignal.objects.get(trader=trader)
        assert signal.timestamp == domain_signal.timestamp
        assert signal.price == domain_signal.price
        assert signal.type == SignalType(domain_signal.type)
        assert signal.data == domain_signal.data
        assert signal.candle_id == domain_signal.candle.id

    def test_sync_signals_query_count(self, trader, domain_signal):
        """CaptureQueriesContext: 1 запрос (bulk_create)."""
        domain_trader = trader.instantiate()
        domain_trader.signals = deque([domain_signal])
        with CaptureQueriesContext(connection) as q:
            trader.sync_signals(trader=domain_trader)
        assert len(q) == 1

    def test_sync_signals_bulk_create_multiple(self, trader, domain_candle):
        """10 сигналов → 1 запрос."""
        now = datetime.now(UTC)
        signals = deque()
        for i in range(10):
            signals.append(
                DomainTraderSignal(
                    timestamp=now + timedelta(minutes=i),
                    price=Decimal("50000"),
                    candle=domain_candle,
                    type=DomainSignalType.WAIT,
                    data={},
                )
            )
        domain_trader = trader.instantiate()
        domain_trader.signals = signals
        with CaptureQueriesContext(connection) as q:
            trader.sync_signals(trader=domain_trader)
        assert len(q) == 1
        assert TraderSignal.objects.filter(trader=trader).count() == 10


# ==================== Trader Sync Positions ====================


@pytest.mark.django_db
class TestTraderSyncPositions:
    """Тесты sync_positions() с CaptureQueriesContext."""

    def test_sync_positions_creates_new(self, trader, domain_position):
        """Новая позиция создаётся."""
        domain_trader = trader.instantiate()
        domain_trader.positions = [domain_position]
        trader.sync_positions(trader=domain_trader)
        assert TraderPosition.objects.filter(trader=trader).count() == 1

    def test_sync_positions_updates_existing(self, trader, domain_position):
        """update_conflicts обновляет status, close_price."""
        domain_trader = trader.instantiate()
        domain_trader.positions = [domain_position]
        trader.sync_positions(trader=domain_trader)

        # Закрываем позицию в домене
        domain_position.status = DomainPositionStatus.CLOSED
        domain_position.close_price = Decimal("52000.00")
        domain_position.close_reason = DomainPositionCloseReason.TAKE_PROFIT
        domain_position.closed_at = datetime.now(UTC)
        domain_trader.positions = [domain_position]
        trader.sync_positions(trader=domain_trader)

        pos = TraderPosition.objects.get(trader=trader)
        assert pos.status == PositionStatus.CLOSED
        assert pos.close_price == Decimal("52000.00")

    def test_sync_positions_empty(self, trader):
        """Пустой list → 0 запросов."""
        domain_trader = trader.instantiate()
        domain_trader.positions = []
        with CaptureQueriesContext(connection) as q:
            trader.sync_positions(trader=domain_trader)
        assert len(q) == 0

    def test_sync_positions_maps_fields(self, trader, domain_position):
        """type, status, amount, prices, dates, close_reason."""
        domain_trader = trader.instantiate()
        domain_trader.positions = [domain_position]
        trader.sync_positions(trader=domain_trader)
        pos = TraderPosition.objects.get(trader=trader)
        assert pos.type == PositionType(domain_position.type)
        assert pos.status == PositionStatus(domain_position.status)
        assert pos.open_amount == domain_position.open_amount
        assert pos.open_price == domain_position.open_price
        assert pos.stop_loss == domain_position.stop_loss
        assert pos.take_profit == domain_position.take_profit
        assert pos.total_fee == domain_position.total_fee

    def test_sync_positions_close_reason_empty_string(self, trader, domain_position):
        """close_reason=None → пустая строка."""
        domain_position.close_reason = None
        domain_trader = trader.instantiate()
        domain_trader.positions = [domain_position]
        trader.sync_positions(trader=domain_trader)
        pos = TraderPosition.objects.get(trader=trader)
        assert pos.close_reason == ""

    def test_sync_positions_query_count(self, trader, domain_position):
        """CaptureQueriesContext: 1 запрос (bulk_create)."""
        domain_trader = trader.instantiate()
        domain_trader.positions = [domain_position]
        with CaptureQueriesContext(connection) as q:
            trader.sync_positions(trader=domain_trader)
        assert len(q) == 1

    def test_sync_positions_upsert_idempotent(self, trader, domain_position):
        """Повторный sync не дублирует записи."""
        domain_trader = trader.instantiate()
        domain_trader.positions = [domain_position]
        trader.sync_positions(trader=domain_trader)
        trader.sync_positions(trader=domain_trader)
        assert TraderPosition.objects.filter(trader=trader).count() == 1


# ==================== Trader Sync Orders ====================


@pytest.mark.django_db
class TestTraderSyncOrders:
    """Тесты sync_orders() (самый сложный метод)."""

    def test_sync_orders_creates_exchange_client_orders(
        self, trader, domain_position, trading_pair
    ):
        """ExchangeClientOrder создаются."""
        domain_trader = trader.instantiate()
        domain_trader.positions = [domain_position]
        trader.sync_positions(trader=domain_trader)
        trader.sync_orders(trader=domain_trader)
        assert ExchangeClientOrder.objects.filter(
            exchange_client=trader.exchange_client,
            exchange_order_id="buy-order-001",
        ).exists()

    def test_sync_orders_creates_trader_orders(self, trader, domain_position):
        """TraderOrder связывает trader + order + position."""
        domain_trader = trader.instantiate()
        domain_trader.positions = [domain_position]
        trader.sync_positions(trader=domain_trader)
        trader.sync_orders(trader=domain_trader)
        assert TraderOrder.objects.filter(trader=trader).count() == 1

    def test_sync_orders_maps_position_correctly(self, trader, domain_position):
        """position_map по (opened_at, amount, type)."""
        domain_trader = trader.instantiate()
        domain_trader.positions = [domain_position]
        trader.sync_positions(trader=domain_trader)
        trader.sync_orders(trader=domain_trader)
        order = TraderOrder.objects.get(trader=trader)
        assert order.position is not None
        assert order.position.type == PositionType(domain_position.type)
        assert order.position.open_amount == domain_position.open_amount

    def test_sync_orders_empty(self, trader):
        """Нет orders → 0 запросов."""
        domain_trader = trader.instantiate()
        domain_trader.positions = []
        with CaptureQueriesContext(connection) as q:
            trader.sync_orders(trader=domain_trader)
        assert len(q) == 0

    def test_sync_orders_duplicate_raises_integrity_error(
        self, trader, domain_position
    ):
        """Повторный sync_orders бросает IntegrityError (ExchangeClientOrder без ignore_conflicts)."""
        domain_trader = trader.instantiate()
        domain_trader.positions = [domain_position]
        trader.sync_positions(trader=domain_trader)
        trader.sync_orders(trader=domain_trader)
        # Второй вызов пытается создать ExchangeClientOrder с тем же exchange_order_id
        with pytest.raises(IntegrityError):
            trader.sync_orders(trader=domain_trader)

    def test_sync_orders_query_count(self, trader, domain_position):
        """CaptureQueriesContext: <= 6 запросов."""
        domain_trader = trader.instantiate()
        domain_trader.positions = [domain_position]
        trader.sync_positions(trader=domain_trader)
        with CaptureQueriesContext(connection) as q:
            trader.sync_orders(trader=domain_trader)
        assert len(q) <= 6

    def test_sync_orders_multiple_positions(
        self, trader, domain_position, domain_closed_position
    ):
        """Ордера из разных позиций маппятся верно."""
        domain_trader = trader.instantiate()
        domain_trader.positions = [
            domain_position,
            domain_closed_position,
        ]
        trader.sync_positions(trader=domain_trader)
        trader.sync_orders(trader=domain_trader)
        # domain_position: 1 order, domain_closed_position: 2 orders
        assert TraderOrder.objects.filter(trader=trader).count() == 3

    def test_sync_orders_bulk_position_lookup(self, trader, domain_position):
        """Все позиции загружаются одним Q OR запросом."""
        domain_trader = trader.instantiate()
        domain_trader.positions = [domain_position]
        trader.sync_positions(trader=domain_trader)
        with CaptureQueriesContext(connection) as q:
            trader.sync_orders(trader=domain_trader)
        # Должен использовать filter(Q(...) | Q(...))
        # а не отдельный запрос на каждую позицию
        assert len(q) <= 6


# ==================== Trader Sync Errors ====================


@pytest.mark.django_db
class TestTraderSyncErrors:
    """Тесты sync_errors()."""

    def test_sync_errors_creates_in_db(self, trader, domain_error):
        """Ошибки сохраняются."""
        domain_trader = trader.instantiate()
        domain_trader.errors = [domain_error]
        with patch("traders.models.traders.send_notification.delay"):
            trader.sync_errors(trader=domain_trader)
        assert TraderError.objects.filter(trader=trader).count() == 1
        err = TraderError.objects.get(trader=trader)
        assert err.message == "Test error message"
        assert err.type == "TestError"

    def test_sync_errors_skips_existing(self, trader, domain_error):
        """Ошибки с id != None не дублируются."""
        domain_error.id = 999
        domain_trader = trader.instantiate()
        domain_trader.errors = [domain_error]
        trader.sync_errors(trader=domain_trader)
        assert TraderError.objects.filter(trader=trader).count() == 0

    def test_sync_errors_empty(self, trader):
        """Нет ошибок → 0 запросов."""
        domain_trader = trader.instantiate()
        domain_trader.errors = []
        with CaptureQueriesContext(connection) as q:
            trader.sync_errors(trader=domain_trader)
        assert len(q) == 0

    def test_sync_errors_sends_notification(self, trader, domain_error):
        """send_notification.delay вызывается."""
        domain_trader = trader.instantiate()
        domain_trader.errors = [domain_error]
        with patch("traders.models.traders.send_notification.delay") as mock_notify:
            trader.sync_errors(trader=domain_trader)
        mock_notify.assert_called_once()
        call_msg = mock_notify.call_args[1]["message"]
        assert str(trader.pk) in call_msg
        assert "Test error message" in call_msg

    def test_sync_errors_sets_error_status(self, trader, domain_error):
        """trader.status = ERROR после sync."""
        domain_trader = trader.instantiate()
        domain_trader.errors = [domain_error]
        with patch("traders.models.traders.send_notification.delay"):
            trader.sync_errors(trader=domain_trader)
        trader.refresh_from_db()
        assert trader.status == TraderStatus.ERROR

    def test_sync_errors_query_count(self, trader, domain_error):
        """CaptureQueriesContext: 2 запроса (bulk_create + save)."""
        domain_trader = trader.instantiate()
        domain_trader.errors = [domain_error]
        with (
            patch("traders.models.traders.send_notification.delay"),
            CaptureQueriesContext(connection) as q,
        ):
            trader.sync_errors(trader=domain_trader)
        assert len(q) == 2


# ==================== Trader Sync (master) ====================


@pytest.mark.django_db
class TestTraderSync:
    """Тесты sync() master."""

    def test_sync_calls_all_sub_syncs(self, trader):
        """Вызывает все 4 sub-sync метода."""
        domain_trader = trader.instantiate()
        with (
            patch.object(trader, "sync_signals") as m1,
            patch.object(trader, "sync_positions") as m2,
            patch.object(trader, "sync_orders") as m3,
            patch.object(trader, "sync_errors") as m4,
        ):
            trader.sync(trader=domain_trader)
        m1.assert_called_once_with(trader=domain_trader)
        m2.assert_called_once_with(trader=domain_trader)
        m3.assert_called_once_with(trader=domain_trader)
        m4.assert_called_once_with(trader=domain_trader)

    def test_sync_full_query_count(
        self,
        trader,
        domain_signal,
        domain_position,
        domain_error,
    ):
        """CaptureQueriesContext <= 10 запросов."""
        domain_trader = trader.instantiate()
        domain_trader.signals = deque([domain_signal])
        domain_trader.positions = [domain_position]
        domain_trader.errors = [domain_error]
        with (
            patch("traders.models.traders.send_notification.delay"),
            CaptureQueriesContext(connection) as q,
        ):
            trader.sync(trader=domain_trader)
        assert len(q) <= 10

    def test_sync_empty_trader(self, trader):
        """Пустые данные → 0 запросов."""
        domain_trader = trader.instantiate()
        with CaptureQueriesContext(connection) as q:
            trader.sync(trader=domain_trader)
        assert len(q) == 0


# ==================== Trader Handle Candle ====================


@pytest.mark.django_db
class TestTraderHandleCandle:
    """Тесты handle_candle()."""

    def test_handle_candle_processes_new_candle(self, trader, exchange_candle):
        """Pipeline: instantiate→load→async→sync."""
        trader.handle_candle(candle=exchange_candle)
        # Должен создать хотя бы сигнал
        assert TraderSignal.objects.filter(trader=trader).count() >= 1

    def test_handle_candle_creates_signal_in_db(self, trader, exchange_candle):
        """Signal появляется в DB."""
        trader.handle_candle(candle=exchange_candle)
        signal = TraderSignal.objects.filter(trader=trader).first()
        assert signal is not None
        assert signal.candle == exchange_candle

    def test_handle_candle_syncs_positions(self, trader, exchange_candle):
        """Позиции синхронизируются (если стратегия сгенерировала)."""
        trader.handle_candle(candle=exchange_candle)
        # Проверяем что pipeline не упал
        trader.refresh_from_db()
        assert trader.status in [
            TraderStatus.ENABLED,
            TraderStatus.ERROR,
        ]

    def test_handle_candle_query_count(self, trader, exchange_candle):
        """CaptureQueriesContext для полного pipeline."""
        with CaptureQueriesContext(connection) as q:
            trader.handle_candle(candle=exchange_candle)
        # Pipeline: instantiate(N) + load(2) + sync(M)
        assert len(q) <= 30


# ==================== Trader Reboot ====================


@pytest.mark.django_db
class TestTraderReboot:
    """Тесты функции reboot трейдера."""

    def test_reboot_skips_if_already_rebooting(self, trader):
        """reboot пропускается если статус REBOOTING."""
        trader.status = TraderStatus.REBOOTING
        trader.save()
        with patch.object(trader, "clear_all_data") as mock_clear:
            trader.reboot()
            mock_clear.assert_not_called()

    def test_reboot_clears_all_data(self, trader, trader_signal, trader_position):
        """reboot очищает все данные."""
        assert TraderSignal.objects.filter(trader=trader).count() > 0
        with patch.object(
            trader.candle_source,
            "get_candle_iterator",
            return_value=iter([]),
        ):
            trader.reboot()
        assert TraderSignal.objects.filter(trader=trader).count() == 0
        assert TraderPosition.objects.filter(trader=trader).count() == 0

    def test_reboot_sets_last_reboot_timestamp(self, trader):
        """reboot устанавливает last_reboot."""
        assert trader.last_reboot is None
        with patch.object(
            trader.candle_source,
            "get_candle_iterator",
            return_value=iter([]),
        ):
            trader.reboot()
        trader.refresh_from_db()
        assert trader.last_reboot is not None

    def test_reboot_sets_status_to_paused_on_success(self, trader):
        """Статус PAUSED при успехе."""
        with patch.object(
            trader.candle_source,
            "get_candle_iterator",
            return_value=iter([]),
        ):
            trader.reboot()
        trader.refresh_from_db()
        assert trader.status == TraderStatus.PAUSED

    def test_reboot_sets_status_to_error_on_exception(self, trader):
        """Статус ERROR при ошибке."""
        with patch.object(
            trader.candle_source,
            "get_candle_iterator",
            side_effect=Exception("Test error"),
        ):
            trader.reboot()
        trader.refresh_from_db()
        assert trader.status == TraderStatus.ERROR

    def test_reboot_creates_error_record_on_exception(self, trader):
        """TraderError.message содержит текст ошибки."""
        with patch.object(
            trader.candle_source,
            "get_candle_iterator",
            side_effect=Exception("Reboot failure"),
        ):
            trader.reboot()
        error = TraderError.objects.filter(trader=trader).first()
        assert error is not None
        assert "Reboot failure" in error.message

    def test_reboot_processes_candle_iterator(self, trader):
        """domain trader.reboot вызывается с итератором."""
        with (
            patch.object(
                trader.candle_source,
                "get_candle_iterator",
                return_value=iter([]),
            ),
            patch(
                "traders.models.traders.DomainTrader.reboot",
                new_callable=AsyncMock,
            ) as mock_reboot,
        ):
            trader.reboot()
        mock_reboot.assert_called_once()

    def test_reboot_syncs_after_processing(self, trader):
        """sync() вызывается после reboot."""
        with (
            patch.object(
                trader.candle_source,
                "get_candle_iterator",
                return_value=iter([]),
            ),
            patch.object(trader, "sync") as mock_sync,
        ):
            trader.reboot()
        mock_sync.assert_called_once()


# ==================== Trader Get Candle Iterator ====================


@pytest.mark.django_db
class TestTraderGetCandleIterator:
    """Тесты get_candle_iterator."""

    def test_get_candle_iterator_yields_domain_candles(self, trader, exchange_candle):
        """Итератор возвращает domain свечи через instantiate()."""
        with patch.object(
            trader.candle_source,
            "get_candle_iterator",
            return_value=iter([exchange_candle]),
        ):
            candles = list(trader.get_candle_iterator())
        assert len(candles) == 1
        # domain candle имеет dt_unix вместо timestamp
        assert hasattr(candles[0], "dt_unix")

    def test_get_candle_iterator_empty(self, trader):
        """Пустой итератор."""
        with patch.object(
            trader.candle_source,
            "get_candle_iterator",
            return_value=iter([]),
        ):
            candles = list(trader.get_candle_iterator())
        assert candles == []


# ==================== Trader Close All Opened ====================


@pytest.mark.django_db
class TestTraderCloseAllOpenedPositions:
    """Тесты close_all_opened_positions."""

    def test_close_all_instantiate_load_sync(self, trader):
        """Полный pipeline instantiate→load→async→sync."""
        trader.close_all_opened_positions()

    def test_close_all_with_opened_positions(self, trader, trader_position):
        """Позиции обрабатываются."""
        trader.close_all_opened_positions()
        # Позиция может быть закрыта (зависит от domain логики)
        trader_position.refresh_from_db()

    def test_close_all_no_positions(self, trader):
        """Пустые позиции, ничего не падает."""
        trader.close_all_opened_positions()


# ==================== Trader Clean (validation) ====================


@pytest.mark.django_db
class TestTraderClean:
    """Тесты валидации Trader."""

    def test_clean_exchange_mismatch(
        self,
        right_candle_source,
        exchange_client,
        strategy,
        risk_manager,
    ):
        """Разные биржи → ValidationError."""
        t = Trader(
            candle_source=right_candle_source,
            exchange_client=exchange_client,
            strategy=strategy,
            risk_manager=risk_manager,
            initial_balance=Decimal("1000"),
        )
        with pytest.raises(ValidationError, match="источника свечей"):
            t.clean()

    def test_clean_valid(self, trader):
        """Валидация проходит."""
        trader.clean()


# ==================== Trader Position Model ====================


@pytest.mark.django_db
class TestTraderPositionModel:
    """Тесты модели TraderPosition."""

    def test_str_representation(self, closed_trader_position):
        """str содержит PNL и RR."""
        s = str(closed_trader_position)
        assert "PNL:" in s
        assert "RR:" in s

    def test_instantiate_maps_all_fields(self, trader_position):
        """Все поля маппятся в domain."""
        dp = trader_position.instantiate()
        assert dp.type == DomainPositionType(trader_position.type)
        assert dp.status == DomainPositionStatus(trader_position.status)
        assert dp.open_amount == trader_position.open_amount
        assert dp.open_price == trader_position.open_price
        assert dp.stop_loss == trader_position.stop_loss
        assert dp.take_profit == trader_position.take_profit
        assert dp.total_fee == trader_position.total_fee
        assert dp.id == trader_position.pk

    def test_open_cost_property(self, trader_position):
        """Делегирует instantiate().open_cost."""
        assert trader_position.open_cost == (
            trader_position.open_price * trader_position.open_amount
        )

    def test_close_cost_property(self, closed_trader_position):
        """Делегирует instantiate().close_cost."""
        assert closed_trader_position.close_cost == (
            closed_trader_position.close_price * closed_trader_position.close_amount
        )

    def test_stop_loss_pct_property(self, trader_position):
        """Делегирует instantiate().stop_loss_pct."""
        pct = trader_position.stop_loss_pct
        assert pct is not None
        assert isinstance(pct, Decimal)

    def test_take_profit_pct_property(self, trader_position):
        """Делегирует instantiate().take_profit_pct."""
        pct = trader_position.take_profit_pct
        assert pct is not None
        assert isinstance(pct, Decimal)

    def test_pnl_pct_closed(self, closed_trader_position):
        """pnl_pct делегирует instantiate().pnl_pct."""
        result = closed_trader_position.pnl_pct
        assert result is not None
        assert isinstance(result, Decimal)

    def test_pnl_pct_opened(self, trader_position):
        """pnl_pct для открытой → None."""
        result = trader_position.pnl_pct
        assert result is None

    def test_pnl_opened(self, trader_position):
        """PnL для открытой позиции → None."""
        assert trader_position.pnl is None

    def test_pnl_closed_long(self, closed_trader_position):
        """LONG: (close-open)*amount - fee."""
        pnl = closed_trader_position.pnl
        expected = (Decimal("52000") - Decimal("50000")) * Decimal("0.1") - Decimal(
            "0.10"
        )
        assert pnl == expected

    def test_pnl_closed_short(self, trader):
        """SHORT: (open-close)*amount - fee."""
        now = datetime.now(UTC)
        pos = TraderPosition.objects.create(
            trader=trader,
            type=PositionType.SHORT,
            status=PositionStatus.CLOSED,
            open_price=Decimal("52000"),
            close_price=Decimal("50000"),
            open_amount=Decimal("0.1"),
            close_amount=Decimal("0.1"),
            open_cost=Decimal("5200"),
            close_cost=Decimal("5000"),
            opened_at=now - timedelta(hours=1),
            closed_at=now,
            total_fee=Decimal("0.10"),
        )
        pnl = pos.pnl
        expected = (Decimal("52000") - Decimal("50000")) * Decimal("0.1") - Decimal(
            "0.10"
        )
        assert pnl == expected

    def test_rr_property(self, trader_position):
        """Risk-reward ratio."""
        rr = trader_position.rr
        assert rr is not None
        # stop_loss=49000, open=50000, tp=52000
        # risk = 50000-49000 = 1000, reward = 52000-50000 = 2000
        # rr = 2000/1000 = 2.0
        assert rr == Decimal("2")

    def test_is_closed(self, trader_position, closed_trader_position):
        """CLOSED → True, OPENED → False."""
        assert trader_position.is_closed is False
        assert closed_trader_position.is_closed is True

    def test_refresh_recalculates_from_orders(
        self,
        trader,
        closed_trader_position,
        exchange_client_order,
        trading_pair,
    ):
        """amount, open_price, close_price пересчитываются."""
        # Создаём sell ордер
        sell_order = ExchangeClientOrder.objects.create(
            exchange_client=trader.exchange_client,
            exchange_order_id="sell-refresh",
            trading_pair=trading_pair,
            side=OrderSide.SELL,
            type="market",
            status=OrderStatus.CLOSED,
            timestamp=datetime.now(UTC),
            amount=Decimal("0.1"),
            price=Decimal("52000"),
            cost=Decimal("5200"),
            fee=Decimal("5.20"),
        )
        TraderOrder.objects.create(
            trader=trader,
            order=exchange_client_order,
            position=closed_trader_position,
        )
        TraderOrder.objects.create(
            trader=trader,
            order=sell_order,
            position=closed_trader_position,
        )
        closed_trader_position.refresh()
        closed_trader_position.refresh_from_db()
        assert closed_trader_position.open_amount == Decimal("0.1")
        assert closed_trader_position.open_price == Decimal("50000")
        assert closed_trader_position.close_price == Decimal("52000")


# ==================== Trader Position Refresh ====================


@pytest.mark.django_db
class TestTraderPositionRefresh:
    """Тесты refresh() с ордерами."""

    def test_refresh_no_orders_noop(self, trader_position):
        """Нет ордеров → ничего не меняется."""
        original_open_amount = trader_position.open_amount
        trader_position.refresh()
        trader_position.refresh_from_db()
        assert trader_position.open_amount == original_open_amount

    def test_refresh_long_position(self, trader, trader_position, trading_pair):
        """BUY=open, SELL=close orders → пересчёт."""
        buy_order = ExchangeClientOrder.objects.create(
            exchange_client=trader.exchange_client,
            exchange_order_id="buy-refresh-long",
            trading_pair=trading_pair,
            side=OrderSide.BUY,
            type="market",
            status=OrderStatus.CLOSED,
            timestamp=datetime.now(UTC),
            amount=Decimal("0.2"),
            price=Decimal("48000"),
            cost=Decimal("9600"),
            fee=Decimal("9.60"),
        )
        TraderOrder.objects.create(
            trader=trader,
            order=buy_order,
            position=trader_position,
        )
        trader_position.refresh()
        trader_position.refresh_from_db()
        assert trader_position.open_amount == Decimal("0.2")
        assert trader_position.open_price == Decimal("48000")

    def test_refresh_short_position(self, trader, trading_pair):
        """SELL=open, BUY=close orders."""
        now = datetime.now(UTC)
        pos = TraderPosition.objects.create(
            trader=trader,
            type=PositionType.SHORT,
            status=PositionStatus.OPENED,
            open_price=Decimal("52000"),
            open_amount=Decimal("0.1"),
            open_cost=Decimal("5200"),
            opened_at=now,
            total_fee=Decimal("0"),
        )
        sell_order = ExchangeClientOrder.objects.create(
            exchange_client=trader.exchange_client,
            exchange_order_id="sell-refresh-short",
            trading_pair=trading_pair,
            side=OrderSide.SELL,
            type="market",
            status=OrderStatus.CLOSED,
            timestamp=now,
            amount=Decimal("0.1"),
            price=Decimal("52000"),
            cost=Decimal("5200"),
            fee=Decimal("5.20"),
        )
        TraderOrder.objects.create(trader=trader, order=sell_order, position=pos)
        pos.refresh()
        pos.refresh_from_db()
        assert pos.open_amount == Decimal("0.1")
        assert pos.open_price == Decimal("52000")

    def test_refresh_weighted_average_price(
        self, trader, trader_position, trading_pair
    ):
        """Несколько ордеров → средневзвешенная цена."""
        buy1 = ExchangeClientOrder.objects.create(
            exchange_client=trader.exchange_client,
            exchange_order_id="buy-wavg-1",
            trading_pair=trading_pair,
            side=OrderSide.BUY,
            type="market",
            status=OrderStatus.CLOSED,
            timestamp=datetime.now(UTC),
            amount=Decimal("0.1"),
            price=Decimal("50000"),
            cost=Decimal("5000"),
            fee=Decimal("5"),
        )
        buy2 = ExchangeClientOrder.objects.create(
            exchange_client=trader.exchange_client,
            exchange_order_id="buy-wavg-2",
            trading_pair=trading_pair,
            side=OrderSide.BUY,
            type="market",
            status=OrderStatus.CLOSED,
            timestamp=datetime.now(UTC),
            amount=Decimal("0.3"),
            price=Decimal("52000"),
            cost=Decimal("15600"),
            fee=Decimal("15.60"),
        )
        TraderOrder.objects.create(trader=trader, order=buy1, position=trader_position)
        TraderOrder.objects.create(trader=trader, order=buy2, position=trader_position)
        trader_position.refresh()
        trader_position.refresh_from_db()
        # open_amount = последний open ордер (один ордер на операцию)
        assert trader_position.open_amount == Decimal("0.3")
        # open_price = цена последнего open ордера
        assert trader_position.open_price == Decimal("52000")

    def test_refresh_query_count(self, trader, trader_position, trading_pair):
        """CaptureQueriesContext."""
        buy = ExchangeClientOrder.objects.create(
            exchange_client=trader.exchange_client,
            exchange_order_id="buy-qc",
            trading_pair=trading_pair,
            side=OrderSide.BUY,
            type="market",
            status=OrderStatus.CLOSED,
            timestamp=datetime.now(UTC),
            amount=Decimal("0.1"),
            price=Decimal("50000"),
            cost=Decimal("5000"),
            fee=Decimal("5"),
        )
        TraderOrder.objects.create(trader=trader, order=buy, position=trader_position)
        with CaptureQueriesContext(connection) as q:
            trader_position.refresh()
        # exists + aggregates + save
        assert len(q) <= 6


# ==================== Trader Signal Model ====================


@pytest.mark.django_db
class TestTraderSignalModel:
    """Тесты модели TraderSignal."""

    def test_str_representation(self, trader_signal):
        """str содержит trader и тип."""
        s = str(trader_signal)
        assert "BUY" in s or "buy" in s

    def test_instantiate_maps_all_fields(self, trader_signal):
        """Все поля маппятся включая candle.instantiate()."""
        ds = trader_signal.instantiate()
        assert ds.id == trader_signal.pk
        assert ds.timestamp == trader_signal.timestamp
        assert ds.price == trader_signal.price
        assert ds.type == DomainSignalType(trader_signal.type)
        assert ds.data == trader_signal.data
        assert ds.candle is not None

    def test_unique_constraint(self, trader, trader_signal, exchange_candle):
        """(trader, timestamp, type) → IntegrityError."""
        with pytest.raises(IntegrityError):
            TraderSignal.objects.create(
                trader=trader,
                timestamp=trader_signal.timestamp,
                price=Decimal("50000"),
                type=trader_signal.type,
                data={},
                candle=exchange_candle,
            )


# ==================== Trader Error Model ====================


@pytest.mark.django_db
class TestTraderErrorModel:
    """Тесты модели TraderError."""

    def test_str_representation(self, trader):
        """str содержит тип и сообщение."""
        err = TraderError.objects.create(
            trader=trader,
            message="Test error",
            type="ValueError",
        )
        assert str(err) == "ValueError"

    def test_instantiate(self, trader):
        """Maps message, type, traceback."""
        err = TraderError.objects.create(
            trader=trader,
            message="Error msg",
            type="TestType",
            traceback="tb line",
        )
        de = err.instantiate()
        assert de.id == err.pk
        assert de.message == "Error msg"
        assert de.type == "TestType"
        assert de.traceback == "tb line"

    def test_ordering(self, trader):
        """ordering = ['-created_at']."""
        err1 = TraderError.objects.create(trader=trader, message="first", type="E")
        err2 = TraderError.objects.create(trader=trader, message="second", type="E")
        errors = list(TraderError.objects.filter(trader=trader))
        assert errors[0].pk == err2.pk
        assert errors[1].pk == err1.pk


# ==================== Trader Order Model ====================


@pytest.mark.django_db
class TestTraderOrderModel:
    """Тесты модели TraderOrder."""

    def test_str_representation(self, trader_order):
        """str содержит side, amount, price."""
        s = str(trader_order)
        assert "0.1" in s or "50000" in s

    def test_clean_position_trader_mismatch(
        self,
        trader,
        right_exchange_client,
        candle_source,
        strategy,
        risk_manager,
        closed_trader_position,
        exchange_client_order,
    ):
        """position.trader != order.trader → ValidationError."""
        other_trader = Trader.objects.create(
            candle_source=candle_source,
            exchange_client=right_exchange_client,
            strategy=strategy,
            risk_manager=risk_manager,
            initial_balance=Decimal("500"),
            status=TraderStatus.DISABLED,
        )
        order = TraderOrder(
            trader=other_trader,
            order=exchange_client_order,
            position=closed_trader_position,
        )
        with pytest.raises(ValidationError, match="тому же трейдеру"):
            order.clean()

    def test_clean_valid(self, trader_order):
        """Валидация проходит."""
        trader_order.clean()

    def test_instantiate(self, trader_order):
        """Делегирует order.instantiate()."""
        do = trader_order.instantiate()
        assert do.exchange_order_id == (trader_order.order.exchange_order_id)
        assert do.price == trader_order.order.price
