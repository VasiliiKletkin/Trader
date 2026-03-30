"""
Тесты admin аннотаций для Trader (get_queryset с Subquery для PnL).
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory

from exchange_clients.models import ExchangeClientOrder
from exchange_clients.schemas import OrderSide, OrderStatus
from traders.admin.traders import TraderAdmin
from traders.models import Trader, TraderOrder, TraderPosition
from traders.schemas import PositionCloseReason, PositionStatus, PositionType


@pytest.fixture
def admin_site():
    return AdminSite()


@pytest.fixture
def trader_admin(admin_site):
    return TraderAdmin(Trader, admin_site)


@pytest.fixture
def rf():
    return RequestFactory()


def _make_closed_position(
    trader,
    pos_type,
    open_price,
    close_price,
    amount,
    fee,
    opened_delta_hours=2,
    closed_delta_hours=1,
):
    now = datetime.now(UTC)
    return TraderPosition.objects.create(
        trader=trader,
        type=pos_type,
        status=PositionStatus.CLOSED,
        open_price=open_price,
        close_price=close_price,
        amount=amount,
        stop_loss=open_price - Decimal("100"),
        take_profit=close_price,
        opened_at=now - timedelta(hours=opened_delta_hours),
        closed_at=now - timedelta(hours=closed_delta_hours),
        recalculated_at=now,
        total_fee=fee,
        close_reason=PositionCloseReason.TAKE_PROFIT,
    )


def _make_orders_for_position(trader, position, exchange_client, trading_pair, prefix):
    """Создает пару buy+sell ордеров для позиции."""
    if position.type == PositionType.LONG:
        buy_side, sell_side = OrderSide.BUY, OrderSide.SELL
        buy_price, sell_price = position.open_price, position.close_price
    else:
        buy_side, sell_side = OrderSide.SELL, OrderSide.BUY
        buy_price, sell_price = position.open_price, position.close_price

    open_order = ExchangeClientOrder.objects.create(
        exchange_client=exchange_client,
        exchange_order_id=f"{prefix}_open",
        trading_pair=trading_pair,
        side=buy_side,
        status=OrderStatus.CLOSED,
        timestamp=position.opened_at,
        amount=position.amount,
        price=buy_price,
        cost=buy_price * position.amount,
        fee=position.total_fee / 2,
    )
    close_order = ExchangeClientOrder.objects.create(
        exchange_client=exchange_client,
        exchange_order_id=f"{prefix}_close",
        trading_pair=trading_pair,
        side=sell_side,
        status=OrderStatus.CLOSED,
        timestamp=position.closed_at,
        amount=position.amount,
        price=sell_price,
        cost=sell_price * position.amount,
        fee=position.total_fee / 2,
    )
    TraderOrder.objects.create(trader=trader, order=open_order, position=position)
    TraderOrder.objects.create(trader=trader, order=close_order, position=position)


@pytest.mark.django_db
class TestTraderAdminGetQueryset:
    """Тесты аннотаций theoretical_pnl и fact_pnl в admin."""

    def test_no_positions_pnl_zero(self, trader_admin, rf, trader):
        """Без позиций theoretical_pnl и fact_pnl = 0."""
        request = rf.get("/admin/traders/trader/")
        qs = trader_admin.get_queryset(request)
        obj = qs.get(pk=trader.pk)
        assert obj._theoretical_pnl == Decimal("0.00")
        assert obj._fact_pnl == Decimal("0.00")

    def test_theoretical_pnl_long_position(self, trader_admin, rf, trader):
        """LONG: pnl = (close - open) * amount - fee."""
        _make_closed_position(
            trader,
            PositionType.LONG,
            open_price=Decimal("50000"),
            close_price=Decimal("52000"),
            amount=Decimal("0.1"),
            fee=Decimal("10"),
        )
        request = rf.get("/admin/traders/trader/")
        qs = trader_admin.get_queryset(request)
        obj = qs.get(pk=trader.pk)
        # (52000 - 50000) * 0.1 - 10 = 190
        assert obj._theoretical_pnl == Decimal("190")

    def test_theoretical_pnl_short_position(self, trader_admin, rf, trader):
        """SHORT: pnl = (open - close) * amount - fee."""
        _make_closed_position(
            trader,
            PositionType.SHORT,
            open_price=Decimal("52000"),
            close_price=Decimal("50000"),
            amount=Decimal("0.1"),
            fee=Decimal("10"),
        )
        request = rf.get("/admin/traders/trader/")
        qs = trader_admin.get_queryset(request)
        obj = qs.get(pk=trader.pk)
        # sign=-1 => -1*(50000-52000)*0.1 - 10 = 2000*0.1 - 10 = 190
        assert obj._theoretical_pnl == Decimal("190")

    def test_theoretical_pnl_multiple_positions(self, trader_admin, rf, trader):
        """Несколько позиций суммируются."""
        _make_closed_position(
            trader,
            PositionType.LONG,
            open_price=Decimal("50000"),
            close_price=Decimal("51000"),
            amount=Decimal("0.1"),
            fee=Decimal("5"),
        )
        _make_closed_position(
            trader,
            PositionType.SHORT,
            open_price=Decimal("51000"),
            close_price=Decimal("50500"),
            amount=Decimal("0.2"),
            fee=Decimal("10"),
            opened_delta_hours=5,
            closed_delta_hours=4,
        )
        request = rf.get("/admin/traders/trader/")
        qs = trader_admin.get_queryset(request)
        obj = qs.get(pk=trader.pk)
        # LONG: (51000-50000)*0.1 - 5 = 95
        # SHORT: -1*(50500-51000)*0.2 - 10 = 500*0.2 - 10 = 90
        expected = Decimal("95") + Decimal("90")
        assert obj._theoretical_pnl == expected

    def test_opened_positions_excluded_from_pnl(self, trader_admin, rf, trader):
        """Открытые позиции не учитываются в theoretical_pnl."""
        now = datetime.now(UTC)
        TraderPosition.objects.create(
            trader=trader,
            type=PositionType.LONG,
            status=PositionStatus.OPENED,
            open_price=Decimal("50000"),
            amount=Decimal("1"),
            stop_loss=Decimal("49000"),
            take_profit=Decimal("55000"),
            opened_at=now,
            recalculated_at=now,
            total_fee=Decimal("5"),
        )
        request = rf.get("/admin/traders/trader/")
        qs = trader_admin.get_queryset(request)
        obj = qs.get(pk=trader.pk)
        assert obj._theoretical_pnl == Decimal("0.00")

    def test_fact_pnl_with_orders(
        self, trader_admin, rf, trader, exchange_client, trading_pair
    ):
        """fact_pnl считается по ордерам: sell*price*amount - buy*price*amount - fee."""
        position = _make_closed_position(
            trader,
            PositionType.LONG,
            open_price=Decimal("50000"),
            close_price=Decimal("52000"),
            amount=Decimal("0.1"),
            fee=Decimal("10"),
        )
        _make_orders_for_position(
            trader, position, exchange_client, trading_pair, "fact_test"
        )
        request = rf.get("/admin/traders/trader/")
        qs = trader_admin.get_queryset(request)
        obj = qs.get(pk=trader.pk)
        # BUY: -1*50000*0.1 - 5 = -5005
        # SELL: +1*52000*0.1 - 5 = 5195
        # Total: 190
        assert obj._fact_pnl == Decimal("190")

    def test_fact_pnl_no_orders_zero(self, trader_admin, rf, trader):
        """fact_pnl = 0 если нет ордеров (даже при наличии позиций)."""
        _make_closed_position(
            trader,
            PositionType.LONG,
            open_price=Decimal("50000"),
            close_price=Decimal("52000"),
            amount=Decimal("0.1"),
            fee=Decimal("10"),
        )
        request = rf.get("/admin/traders/trader/")
        qs = trader_admin.get_queryset(request)
        obj = qs.get(pk=trader.pk)
        assert obj._fact_pnl == Decimal("0.00")

    def test_display_methods(self, trader_admin, rf, trader):
        """Display методы возвращают округленные значения."""
        _make_closed_position(
            trader,
            PositionType.LONG,
            open_price=Decimal("50000"),
            close_price=Decimal("52000"),
            amount=Decimal("0.1"),
            fee=Decimal("10"),
        )
        request = rf.get("/admin/traders/trader/")
        qs = trader_admin.get_queryset(request)
        obj = qs.get(pk=trader.pk)
        assert trader_admin.theoretical_pnl(obj) == 190
        assert trader_admin.fact_pnl(obj) == 0
