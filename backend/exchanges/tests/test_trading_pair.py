"""Тесты TradingPair.compute_cost / cost_to_amount для spot/linear/inverse."""

from decimal import Decimal

import pytest

from exchanges.domain.schemas import MarketType, TradingPair


@pytest.fixture
def spot_pair() -> TradingPair:
    """BTC/USDT spot: cost = amount * price (quote)."""
    return TradingPair(
        name="BTC/USDT",
        symbol="BTC/USDT",
        base_currency="BTC",
        quote_currency="USDT",
        settle_currency="USDT",
        market_type=MarketType.SPOT,
        is_linear=True,
    )


@pytest.fixture
def linear_pair() -> TradingPair:
    """BTC/USDT:USDT linear futures: cost = amount * price (quote)."""
    return TradingPair(
        name="BTC/USDT",
        symbol="BTC/USDT:USDT",
        base_currency="BTC",
        quote_currency="USDT",
        settle_currency="USDT",
        market_type=MarketType.FUTURES,
        is_linear=True,
        contract_size=Decimal("1"),
    )


@pytest.fixture
def inverse_pair() -> TradingPair:
    """BTC/USD:BTC inverse futures: cost = amount * contract_size / price (base)."""
    return TradingPair(
        name="BTC/USD",
        symbol="BTC/USD:BTC",
        base_currency="BTC",
        quote_currency="USD",
        settle_currency="BTC",
        market_type=MarketType.FUTURES,
        is_linear=False,
        contract_size=Decimal("100"),
    )


class TestComputeCost:
    def test_spot(self, spot_pair):
        """spot: 0.5 BTC @ 40000 = 20000 USDT."""
        cost = spot_pair.compute_cost(Decimal("0.5"), Decimal("40000"))
        assert cost == Decimal("20000")

    def test_linear(self, linear_pair):
        """linear: 0.1 BTC @ 50000 = 5000 USDT."""
        cost = linear_pair.compute_cost(Decimal("0.1"), Decimal("50000"))
        assert cost == Decimal("5000")

    def test_inverse(self, inverse_pair):
        """inverse: 10 * contract_size(100) * 50000 = 50_000_000."""
        cost = inverse_pair.compute_cost(Decimal("10"), Decimal("50000"))
        assert cost == Decimal("50000000")

    def test_inverse_zero_price_returns_zero(self, inverse_pair):
        """inverse: нулевая цена обработана."""
        assert inverse_pair.compute_cost(Decimal("10"), Decimal("0")) == Decimal("0")


class TestCostToAmount:
    def test_spot(self, spot_pair):
        """spot: 20000 USDT / 40000 = 0.5 BTC."""
        amount = spot_pair.cost_to_amount(Decimal("20000"), Decimal("40000"))
        assert amount == Decimal("0.5")

    def test_linear(self, linear_pair):
        """linear: 5000 USDT / 50000 = 0.1 BTC."""
        amount = linear_pair.cost_to_amount(Decimal("5000"), Decimal("50000"))
        assert amount == Decimal("0.1")

    def test_inverse(self, inverse_pair):
        """inverse: 50_000_000 / 50000 / 100 = 10."""
        amount = inverse_pair.cost_to_amount(Decimal("50000000"), Decimal("50000"))
        assert amount == Decimal("10")


class TestRoundTrip:
    @pytest.mark.parametrize(
        "fixture_name",
        ["spot_pair", "linear_pair", "inverse_pair"],
    )
    def test_cost_to_amount_then_compute_cost(self, fixture_name, request):
        """compute_cost(cost_to_amount(c, p), p) == c."""
        pair = request.getfixturevalue(fixture_name)
        price = Decimal("50000")
        original_cost = Decimal("100")
        amount = pair.cost_to_amount(original_cost, price)
        recovered_cost = pair.compute_cost(amount, price)
        assert recovered_cost == original_cost
