"""
Тесты Pydantic-схем доменного слоя arbitrage_traders.
Фокус: computed properties ArbitrageTraderPosition (pnl, costs, is_closed).
"""

from decimal import Decimal

import pytest

from arbitrage_traders.domain.schemas import (
    ArbitrageTraderPosition,
    PositionCloseReason,
    PositionStatus,
    PositionType,
)

# ==================== Helpers ====================


def _make_closed_position(
    left_type=PositionType.LONG,
    right_type=PositionType.SHORT,
    amount=Decimal("1.0"),
    left_open=Decimal("100.00"),
    right_open=Decimal("102.00"),
    left_close=Decimal("105.00"),
    right_close=Decimal("101.00"),
    left_total_fee=Decimal("0.20"),
    right_total_fee=Decimal("0.20"),
) -> ArbitrageTraderPosition:
    return ArbitrageTraderPosition(
        type=left_type,
        left_type=left_type,
        right_type=right_type,
        status=PositionStatus.CLOSED,
        amount=amount,
        left_open_price=left_open,
        right_open_price=right_open,
        left_close_price=left_close,
        right_close_price=right_close,
        left_total_fee=left_total_fee,
        right_total_fee=right_total_fee,
        close_reason=PositionCloseReason.STRATEGY,
    )


def _make_opened_position(
    left_type=PositionType.LONG,
    right_type=PositionType.SHORT,
    amount=Decimal("1.0"),
    left_open=Decimal("100.00"),
    right_open=Decimal("102.00"),
) -> ArbitrageTraderPosition:
    return ArbitrageTraderPosition(
        type=left_type,
        left_type=left_type,
        right_type=right_type,
        status=PositionStatus.OPENED,
        amount=amount,
        left_open_price=left_open,
        right_open_price=right_open,
    )


# ==================== PnL ====================


class TestArbitrageTraderPositionPnl:
    """Тесты PnL свойств ArbitrageTraderPosition."""

    def test_left_pnl_long_positive(self):
        """LONG left: (close - open) * amount - fee."""
        pos = _make_closed_position(
            left_type=PositionType.LONG,
            left_open=Decimal("100"),
            left_close=Decimal("105"),
            amount=Decimal("2.0"),
        )
        # (105 - 100) * 2 - 0.20 = 9.80
        assert pos.left_pnl == Decimal("9.80")

    def test_left_pnl_short_positive(self):
        """SHORT left: (open - close) * amount - fee."""
        pos = _make_closed_position(
            left_type=PositionType.SHORT,
            right_type=PositionType.LONG,
            left_open=Decimal("105"),
            left_close=Decimal("100"),
            amount=Decimal("2.0"),
        )
        # (105 - 100) * 2 - 0.20 = 9.80
        assert pos.left_pnl == Decimal("9.80")

    def test_left_pnl_none_without_close_price(self):
        """left_pnl = None когда нет close_price."""
        pos = _make_opened_position()
        assert pos.left_pnl is None

    def test_right_pnl_long(self):
        """LONG right: (close - open) * amount - fee."""
        pos = _make_closed_position(
            right_type=PositionType.LONG,
            right_open=Decimal("100"),
            right_close=Decimal("103"),
            amount=Decimal("1.0"),
        )
        # (103 - 100) * 1 - 0.20 = 2.80
        assert pos.right_pnl == Decimal("2.80")

    def test_right_pnl_short(self):
        """SHORT right: (open - close) * amount - fee."""
        pos = _make_closed_position(
            right_type=PositionType.SHORT,
            right_open=Decimal("102"),
            right_close=Decimal("101"),
            amount=Decimal("1.0"),
        )
        # (102 - 101) * 1 - 0.20 = 0.80
        assert pos.right_pnl == Decimal("0.80")

    def test_right_pnl_none_without_close_price(self):
        """right_pnl = None когда нет close_price."""
        pos = _make_opened_position()
        assert pos.right_pnl is None

    def test_pnl_closed_with_fee(self):
        """pnl = left_pnl + right_pnl для CLOSED."""
        # left: (105-100)*1 - 0.20 = 4.80, right: (102-101)*1 - 0.20 = 0.80
        pos = _make_closed_position()
        assert pos.pnl == Decimal("5.60")  # 4.80 + 0.80

    def test_pnl_none_for_opened(self):
        """pnl = None для OPENED позиции."""
        pos = _make_opened_position()
        assert pos.pnl is None


# ==================== PnL Percent ====================


class TestArbitrageTraderPositionPnlPct:
    """Тесты pnl_pct свойства."""

    def test_pnl_pct_correct_for_closed(self):
        """pnl_pct = 100 * pnl / open_cost."""
        pos = _make_closed_position()
        # open_cost = 100*1 + 102*1 = 202, pnl = 5.60
        expected = 100 * Decimal("5.60") / Decimal("202")
        assert pos.pnl_pct == pytest.approx(expected, rel=Decimal("0.01"))

    def test_pnl_pct_none_for_opened(self):
        """pnl_pct = None для opened позиции."""
        pos = _make_opened_position()
        assert pos.pnl_pct is None

    def test_pnl_pct_none_when_no_open_prices(self):
        """pnl_pct = None когда open_cost = None."""
        pos = ArbitrageTraderPosition(
            type=PositionType.LONG,
            left_type=PositionType.LONG,
            right_type=PositionType.SHORT,
            status=PositionStatus.CLOSED,
            amount=Decimal("1.0"),
        )
        assert pos.pnl_pct is None

    def test_pnl_pct_none_when_pnl_none(self):
        """pnl_pct = None когда pnl = None (нет close_price)."""
        pos = ArbitrageTraderPosition(
            type=PositionType.LONG,
            left_type=PositionType.LONG,
            right_type=PositionType.SHORT,
            status=PositionStatus.CLOSED,
            amount=Decimal("1.0"),
            left_open_price=Decimal("100"),
            right_open_price=Decimal("102"),
            left_close_price=Decimal("105"),
            # right_close_price отсутствует → pnl = None
        )
        assert pos.pnl_pct is None


# ==================== Costs ====================


class TestArbitrageTraderPositionCosts:
    """Тесты свойств стоимости позиции."""

    def test_left_open_cost(self):
        """left_open_cost = left_open_price * amount."""
        pos = _make_opened_position(left_open=Decimal("100"), amount=Decimal("2.0"))
        assert pos.left_open_cost == Decimal("200.00")

    def test_left_open_cost_none(self):
        """left_open_cost = None без left_open_price."""
        pos = ArbitrageTraderPosition(
            type=PositionType.LONG,
            left_type=PositionType.LONG,
            right_type=PositionType.SHORT,
            status=PositionStatus.OPENED,
            amount=Decimal("1.0"),
        )
        assert pos.left_open_cost is None

    def test_right_open_cost(self):
        """right_open_cost = right_open_price * amount."""
        pos = _make_opened_position(right_open=Decimal("102"), amount=Decimal("3.0"))
        assert pos.right_open_cost == Decimal("306.00")

    def test_open_cost_sum(self):
        """open_cost = left_open_cost + right_open_cost."""
        pos = _make_opened_position(
            left_open=Decimal("100"), right_open=Decimal("102"), amount=Decimal("1.0")
        )
        assert pos.open_cost == Decimal("202.00")

    def test_open_cost_none_when_both_missing(self):
        """open_cost = None когда обе стороны None."""
        pos = ArbitrageTraderPosition(
            type=PositionType.LONG,
            left_type=PositionType.LONG,
            right_type=PositionType.SHORT,
            status=PositionStatus.OPENED,
            amount=Decimal("1.0"),
        )
        assert pos.open_cost is None

    def test_left_close_cost(self):
        """left_close_cost = left_close_price * amount."""
        pos = _make_closed_position(left_close=Decimal("105"), amount=Decimal("2.0"))
        assert pos.left_close_cost == Decimal("210.00")

    def test_right_close_cost(self):
        """right_close_cost = right_close_price * amount."""
        pos = _make_closed_position(right_close=Decimal("101"), amount=Decimal("2.0"))
        assert pos.right_close_cost == Decimal("202.00")

    def test_close_cost_sum(self):
        """close_cost = left_close_cost + right_close_cost."""
        pos = _make_closed_position(
            left_close=Decimal("105"), right_close=Decimal("101"), amount=Decimal("1.0")
        )
        assert pos.close_cost == Decimal("206.00")


# ==================== is_closed ====================


class TestArbitrageTraderPositionIsClosed:
    """Тесты is_closed свойства."""

    def test_is_closed_true(self):
        """is_closed = True для CLOSED."""
        pos = _make_closed_position()
        assert pos.is_closed is True

    def test_is_closed_false(self):
        """is_closed = False для OPENED."""
        pos = _make_opened_position()
        assert pos.is_closed is False


# ==================== Edge Cases ====================


class TestArbitrageTraderPositionEdgeCases:
    """Крайние случаи ArbitrageTraderPosition."""

    def test_pnl_with_zero_fee(self):
        """PnL без комиссии."""
        pos = _make_closed_position(
            left_total_fee=Decimal("0"), right_total_fee=Decimal("0")
        )
        # left LONG: (105-100)*1=5, right SHORT: (102-101)*1=1
        assert pos.pnl == Decimal("6.00")

    def test_pnl_negative_losing_position(self):
        """PnL отрицательный для убыточной позиции."""
        pos = _make_closed_position(
            left_type=PositionType.LONG,
            right_type=PositionType.SHORT,
            left_open=Decimal("100"),
            left_close=Decimal("95"),  # убыток на left: -5
            right_open=Decimal("102"),
            right_close=Decimal("103"),  # убыток на right SHORT: (102-103)*1 = -1
            left_total_fee=Decimal("0.20"),
            right_total_fee=Decimal("0.20"),
        )
        # left_pnl = (95-100)*1 = -5, right_pnl = (102-103)*1 = -1, pnl = -5 + (-1) - 0.40 = -6.40
        assert pos.pnl == Decimal("-6.40")

    def test_arbitrage_pair_long_left_short_right(self):
        """Типичный арбитраж: LONG left + SHORT right."""
        pos = _make_closed_position(
            left_type=PositionType.LONG,
            right_type=PositionType.SHORT,
            left_open=Decimal("100"),
            left_close=Decimal("103"),
            right_open=Decimal("105"),
            right_close=Decimal("102"),
            amount=Decimal("0.5"),
            left_total_fee=Decimal("0.05"),
            right_total_fee=Decimal("0.05"),
        )
        # left: (103-100)*0.5 = 1.5, right: (105-102)*0.5 = 1.5
        assert pos.pnl == Decimal("2.90")  # 1.5 + 1.5 - 0.10
