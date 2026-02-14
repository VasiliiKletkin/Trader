"""
Общие фикстуры для доменных тестов arbitrage_traders.

Все фикстуры — чистые Python-объекты без обращения к БД.
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from arbitrage_traders.domain.risk_managers import (
    PSAllInArbitrageRiskManager,
    PSPercentArbitrageRiskManager,
)
from arbitrage_traders.domain.schemas import (
    ArbitrageTraderPosition,
    ArbitrageTraderSignal,
    PositionCloseReason,
    PositionStatus,
    PositionType,
    SignalType,
    SimpleArbitrageData,
)
from arbitrage_traders.domain.strategies import SimpleArbitrageStrategy
from arbitrage_traders.domain.traders import ArbitrageTrader
from exchange_clients.domain import (
    AbstractExchangeClient,
    ExchangeClientOrder,
    OrderSide,
    OrderStatus,
    OrderType,
)
from exchanges.domain import ExchangeCandle, Timeframe, TradingPair

# ==================== Trading Pair & Timeframe (переопределяем ORM-фикстуры) =======


@pytest.fixture
def trading_pair() -> TradingPair:
    """Чистая domain TradingPair (не ORM)."""
    return TradingPair(
        name="BTC/USDT",
        symbol="BTC/USDT:USDT",
        min_amount=Decimal("0.001"),
        max_amount=Decimal("1000"),
        fee_percent=Decimal("0.1"),
    )


@pytest.fixture
def timeframe() -> Timeframe:
    """Стандартный таймфрейм 1 час."""
    return Timeframe.ONE_HOUR


# ==================== Candles ====================


@pytest.fixture
def left_candle() -> ExchangeCandle:
    """Свеча с первой биржи, close=100."""
    ts = int(datetime(2024, 1, 1, 12, 0, tzinfo=UTC).timestamp() * 1000)
    return ExchangeCandle(
        id=1,
        dt_unix=ts,
        open=Decimal("99.00"),
        high=Decimal("101.00"),
        low=Decimal("98.00"),
        close=Decimal("100.00"),
        volume=Decimal("500.00"),
    )


@pytest.fixture
def right_candle() -> ExchangeCandle:
    """Свеча со второй биржи, close=102 (спред ~-1.96%, < open_threshold=1.0)."""
    ts = int(datetime(2024, 1, 1, 12, 0, tzinfo=UTC).timestamp() * 1000)
    return ExchangeCandle(
        id=2,
        dt_unix=ts,
        open=Decimal("101.00"),
        high=Decimal("103.00"),
        low=Decimal("100.00"),
        close=Decimal("102.00"),
        volume=Decimal("500.00"),
    )


@pytest.fixture
def left_candle_high_spread() -> ExchangeCandle:
    """Свеча с первой биржи, close=100 (для большого спреда)."""
    ts = int(datetime(2024, 1, 1, 13, 0, tzinfo=UTC).timestamp() * 1000)
    return ExchangeCandle(
        id=3,
        dt_unix=ts,
        open=Decimal("99.00"),
        high=Decimal("101.00"),
        low=Decimal("98.00"),
        close=Decimal("100.00"),
        volume=Decimal("500.00"),
    )


@pytest.fixture
def right_candle_high_spread() -> ExchangeCandle:
    """Свеча со второй биржи, close=110 (спред ~-9.09%, > open_threshold)."""
    ts = int(datetime(2024, 1, 1, 13, 0, tzinfo=UTC).timestamp() * 1000)
    return ExchangeCandle(
        id=4,
        dt_unix=ts,
        open=Decimal("109.00"),
        high=Decimal("111.00"),
        low=Decimal("108.00"),
        close=Decimal("110.00"),
        volume=Decimal("500.00"),
    )


# ==================== Strategy & Risk Manager ====================


@pytest.fixture
def strategy() -> SimpleArbitrageStrategy:
    """Стандартная стратегия: open_threshold=1.0, close_threshold=0.2."""
    return SimpleArbitrageStrategy(open_threshold=1.0, close_threshold=0.2)


@pytest.fixture
def risk_manager_allin() -> PSAllInArbitrageRiskManager:
    """Риск-менеджер: весь баланс."""
    return PSAllInArbitrageRiskManager()


@pytest.fixture
def risk_manager_percent() -> PSPercentArbitrageRiskManager:
    """Риск-менеджер: 50% от баланса."""
    return PSPercentArbitrageRiskManager(position_size_percent=50.0)


# ==================== Mock Exchange Clients ====================


def _make_order(
    side: OrderSide,
    price: Decimal,
    amount: Decimal,
    trading_pair: TradingPair,
) -> ExchangeClientOrder:
    """Вспомогательная: создаёт ExchangeClientOrder."""
    return ExchangeClientOrder(
        id=1,
        timestamp=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
        status=OrderStatus.CLOSED,
        trading_pair=trading_pair,
        exchange_order_id="test-order-123",
        type=OrderType.MARKET,
        side=side,
        price=price,
        amount=amount,
        fee=price * amount * Decimal("0.001"),
        cost=price * amount,
    )


@pytest.fixture
def mock_left_exchange_client(trading_pair) -> AsyncMock:
    """Мок левого exchange client."""
    client = AsyncMock(spec=AbstractExchangeClient)
    client.create_market_order = AsyncMock(
        side_effect=lambda trading_pair, side, amount, params=None: _make_order(
            side=side,
            price=Decimal("100.00"),
            amount=amount,
            trading_pair=trading_pair,
        )
    )
    return client


@pytest.fixture
def mock_right_exchange_client(trading_pair) -> AsyncMock:
    """Мок правого exchange client."""
    client = AsyncMock(spec=AbstractExchangeClient)
    client.create_market_order = AsyncMock(
        side_effect=lambda trading_pair, side, amount, params=None: _make_order(
            side=side,
            price=Decimal("102.00"),
            amount=amount,
            trading_pair=trading_pair,
        )
    )
    return client


# ==================== Trader ====================


@pytest.fixture
def trader(
    trading_pair,
    timeframe,
    mock_left_exchange_client,
    mock_right_exchange_client,
    strategy,
    risk_manager_allin,
) -> ArbitrageTrader:
    """Арбитражный трейдер с моками exchange client."""
    return ArbitrageTrader(
        trading_pair=trading_pair,
        timeframe=timeframe,
        left_exchange_client=mock_left_exchange_client,
        right_exchange_client=mock_right_exchange_client,
        strategy=strategy,
        risk_manager=risk_manager_allin,
        use_fixed_balance=True,
        initial_balance=Decimal("1000.00"),
        balance=Decimal("1000.00"),
        check_drawdown=True,
        max_drawdown_pct=Decimal("10.0"),
        max_positions_count=1,
        create_new_orders=False,
    )


# ==================== Signals ====================


@pytest.fixture
def buy_signal(left_candle, right_candle) -> ArbitrageTraderSignal:
    """Сигнал BUY (left) / SELL (right)."""
    return ArbitrageTraderSignal(
        timestamp=left_candle.timestamp,
        left_price=Decimal("100.00"),
        right_price=Decimal("102.00"),
        left_type=SignalType.BUY,
        right_type=SignalType.SELL,
        left_candle=left_candle,
        right_candle=right_candle,
        data=SimpleArbitrageData(
            spread=-1.96, price_first=100.0, price_second=102.0
        ).model_dump(),
    )


@pytest.fixture
def sell_signal(left_candle, right_candle) -> ArbitrageTraderSignal:
    """Сигнал SELL (left) / BUY (right)."""
    return ArbitrageTraderSignal(
        timestamp=left_candle.timestamp,
        left_price=Decimal("102.00"),
        right_price=Decimal("100.00"),
        left_type=SignalType.SELL,
        right_type=SignalType.BUY,
        left_candle=left_candle,
        right_candle=right_candle,
        data=SimpleArbitrageData(
            spread=2.0, price_first=102.0, price_second=100.0
        ).model_dump(),
    )


@pytest.fixture
def wait_signal(left_candle, right_candle) -> ArbitrageTraderSignal:
    """Сигнал WAIT / WAIT."""
    return ArbitrageTraderSignal(
        timestamp=left_candle.timestamp,
        left_price=Decimal("100.00"),
        right_price=Decimal("100.50"),
        left_type=SignalType.WAIT,
        right_type=SignalType.WAIT,
        left_candle=left_candle,
        right_candle=right_candle,
        data=SimpleArbitrageData(
            spread=-0.5, price_first=100.0, price_second=100.5
        ).model_dump(),
    )


# ==================== Positions ====================


@pytest.fixture
def opened_position() -> ArbitrageTraderPosition:
    """Открытая LONG позиция (left LONG, right SHORT)."""
    return ArbitrageTraderPosition(
        type=PositionType.LONG,
        left_type=PositionType.LONG,
        right_type=PositionType.SHORT,
        status=PositionStatus.OPENED,
        amount=Decimal("1.0"),
        left_open_price=Decimal("100.00"),
        right_open_price=Decimal("102.00"),
        total_fee=Decimal("0.20"),
        opened_at=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
    )


@pytest.fixture
def closed_position() -> ArbitrageTraderPosition:
    """Закрытая LONG позиция с прибылью."""
    return ArbitrageTraderPosition(
        type=PositionType.LONG,
        left_type=PositionType.LONG,
        right_type=PositionType.SHORT,
        status=PositionStatus.CLOSED,
        amount=Decimal("1.0"),
        left_open_price=Decimal("100.00"),
        right_open_price=Decimal("102.00"),
        left_close_price=Decimal("105.00"),
        right_close_price=Decimal("101.00"),
        total_fee=Decimal("0.40"),
        opened_at=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
        closed_at=datetime(2024, 1, 1, 16, 0, tzinfo=UTC),
        close_reason=PositionCloseReason.STRATEGY,
    )
