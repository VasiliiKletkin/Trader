"""
Фикстуры для тестов traders app.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from candle_sources.models import CandleSource
from exchange_clients.domain import ExchangeClientOrder as DomainExchangeClientOrder
from exchange_clients.domain import OrderSide as DomainOrderSide
from exchange_clients.domain import OrderStatus as DomainOrderStatus
from exchange_clients.domain import OrderType as DomainOrderType
from exchange_clients.models import ExchangeClient, ExchangeClientOrder
from exchange_clients.schemas import OrderSide, OrderStatus
from exchanges.domain import BybitExchange
from exchanges.domain import ExchangeCandle as DomainExchangeCandle
from exchanges.domain import MarketType as DomainMarketType
from exchanges.domain import TradingPair as DomainTradingPair
from exchanges.domain.exchanges import BinanceExchange
from exchanges.models import Exchange, ExchangeCandle, ExchangeTradingPair, TradingPair
from exchanges.schemas import Timeframe
from traders.domain.risk_managers import SLPercentTPPercentPSAllInRiskManager
from traders.domain.schemas import PositionCloseReason as DomainPositionCloseReason
from traders.domain.schemas import PositionStatus as DomainPositionStatus
from traders.domain.schemas import PositionType as DomainPositionType
from traders.domain.schemas import SignalType as DomainSignalType
from traders.domain.schemas import TraderError as DomainTraderError
from traders.domain.schemas import TraderPosition as DomainTraderPosition
from traders.domain.schemas import TraderSignal as DomainTraderSignal
from traders.domain.strategies import MoneyFlowIndexStrategy
from traders.models import (
    RiskManager,
    Strategy,
    Trader,
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


@pytest.fixture(autouse=True)
def _mock_bus_client():
    with patch(
        "traders.models.traders.get_bus_client",
        return_value=MagicMock(),
    ):
        yield


@pytest.fixture
def exchange() -> Exchange:
    """Создает тестовую биржу."""
    exchange, _ = Exchange.objects.get_or_create(
        class_name=BybitExchange.__name__,
        defaults={"name": "Bybit Test"},
    )
    return exchange


@pytest.fixture
def trading_pair() -> TradingPair:
    """Создает тестовую торговую пару."""
    pair, _ = TradingPair.objects.get_or_create(
        name="BTC/USDT",
    )
    return pair


@pytest.fixture
def exchange_trading_pair(
    exchange: Exchange, trading_pair: TradingPair
) -> ExchangeTradingPair:
    """Создает связку биржа-торговая пара."""
    pair, _ = ExchangeTradingPair.objects.get_or_create(
        exchange=exchange,
        trading_pair=trading_pair,
        defaults={
            "symbol": "BTC/USDT:USDT",
        },
    )
    return pair


@pytest.fixture
def right_exchange() -> Exchange:
    """Создает вторую тестовую биржу."""
    exchange, _ = Exchange.objects.get_or_create(
        class_name=BinanceExchange.__name__,
        defaults={"name": "Binance Test"},
    )
    return exchange


@pytest.fixture
def exchange_client(exchange: Exchange) -> ExchangeClient:
    """Создает тестового клиента биржи."""
    return ExchangeClient.objects.create(
        exchange=exchange,
        name="Test Client",
        arguments={"api_key": "test_api_key", "api_secret": "test_api_secret"},
    )


@pytest.fixture
def right_exchange_client(right_exchange: Exchange) -> ExchangeClient:
    """Создает второго клиента биржи."""
    return ExchangeClient.objects.create(
        exchange=right_exchange,
        name="Test Client 2",
        arguments={"api_key": "test_api_key_2", "api_secret": "test_api_secret_2"},
    )


@pytest.fixture
def candle_source(exchange: Exchange, trading_pair: TradingPair) -> CandleSource:
    """Создает источник свечей."""
    return CandleSource.objects.create(
        exchange=exchange,
        trading_pair=trading_pair,
        timeframe=Timeframe.ONE_HOUR,
    )


@pytest.fixture
def right_candle_source(
    right_exchange: Exchange, trading_pair: TradingPair
) -> CandleSource:
    """Создает источник свечей на другой бирже."""
    return CandleSource.objects.create(
        exchange=right_exchange,
        trading_pair=trading_pair,
        timeframe=Timeframe.ONE_HOUR,
    )


@pytest.fixture
def strategy() -> Strategy:
    """Создает стратегию."""
    return Strategy.objects.create(
        name="Test Strategy",
        class_name=MoneyFlowIndexStrategy.__name__,
        arguments={"period": 14, "overbought": 80, "oversold": 20, "median": 50},
    )


@pytest.fixture
def risk_manager() -> RiskManager:
    """Создает риск-менеджер."""
    return RiskManager.objects.create(
        name="Test Risk Manager",
        class_name=SLPercentTPPercentPSAllInRiskManager.__name__,
        arguments={"stop_loss_percent": 2.0, "take_profit_percent": 4.0},
    )


@pytest.fixture
def trader(
    candle_source: CandleSource,
    exchange_client: ExchangeClient,
    exchange_trading_pair: ExchangeTradingPair,
    strategy: Strategy,
    risk_manager: RiskManager,
) -> Trader:
    """Создает трейдера."""
    return Trader.objects.create(
        candle_source=candle_source,
        exchange_client=exchange_client,
        strategy=strategy,
        risk_manager=risk_manager,
        initial_balance=Decimal("1000.00"),
        status=TraderStatus.ENABLED,
    )


@pytest.fixture
def exchange_candle(exchange: Exchange, trading_pair: TradingPair) -> ExchangeCandle:
    """Создает свечу биржи."""
    now = datetime.now(UTC)
    return ExchangeCandle.objects.create(
        exchange=exchange,
        trading_pair=trading_pair,
        timeframe=Timeframe.ONE_HOUR,
        timestamp=now,
        open=Decimal("50000.00"),
        high=Decimal("51000.00"),
        low=Decimal("49000.00"),
        close=Decimal("50500.00"),
        volume=Decimal("100.00"),
    )


@pytest.fixture
def trader_signal(trader: Trader, exchange_candle: ExchangeCandle) -> TraderSignal:
    """Создает сигнал трейдера."""
    return TraderSignal.objects.create(
        trader=trader,
        timestamp=datetime.now(UTC),
        price=Decimal("50500.00"),
        type=SignalType.BUY,
        data={},
        candle=exchange_candle,
    )


@pytest.fixture
def trader_position(trader: Trader) -> TraderPosition:
    """Создает позицию трейдера."""
    now = datetime.now(UTC)
    return TraderPosition.objects.create(
        trader=trader,
        type=PositionType.LONG,
        status=PositionStatus.OPENED,
        open_price=Decimal("50000.00"),
        amount=Decimal("0.1"),
        stop_loss=Decimal("49000.00"),
        take_profit=Decimal("52000.00"),
        opened_at=now,
        recalculated_at=now,
        total_fee=Decimal("0.05"),
    )


@pytest.fixture
def closed_trader_position(trader: Trader) -> TraderPosition:
    """Создает закрытую позицию трейдера."""
    now = datetime.now(UTC)
    return TraderPosition.objects.create(
        trader=trader,
        type=PositionType.LONG,
        status=PositionStatus.CLOSED,
        open_price=Decimal("50000.00"),
        close_price=Decimal("52000.00"),
        amount=Decimal("0.1"),
        stop_loss=Decimal("49000.00"),
        take_profit=Decimal("52000.00"),
        opened_at=now - timedelta(hours=1),
        closed_at=now,
        recalculated_at=now,
        total_fee=Decimal("0.10"),
        close_reason=PositionCloseReason.TAKE_PROFIT,
    )


@pytest.fixture
def exchange_client_order(
    exchange_client: ExchangeClient, trading_pair: TradingPair
) -> ExchangeClientOrder:
    """Создает ордер клиента биржи."""
    return ExchangeClientOrder.objects.create(
        exchange_client=exchange_client,
        exchange_order_id="order_123",
        trading_pair=trading_pair,
        side=OrderSide.BUY,
        type="market",
        status=OrderStatus.CLOSED,
        timestamp=datetime.now(UTC),
        amount=Decimal("0.1"),
        price=Decimal("50000.00"),
        cost=Decimal("5000.00"),
        fee=Decimal("5.00"),
    )


# ==================== Domain объекты для sync/load тестов ====================


@pytest.fixture
def domain_trading_pair(trading_pair) -> DomainTradingPair:
    """Domain TradingPair из ORM."""
    return DomainTradingPair(
        name=trading_pair.name,
        symbol="BTC/USDT:USDT",
        base_currency="BTC",
        quote_currency="USDT",
        market_type=DomainMarketType.FUTURES,
        taker_fee=Decimal("0.001"),
        maker_fee=Decimal("0.001"),
    )


@pytest.fixture
def domain_candle(exchange_candle) -> DomainExchangeCandle:
    """Domain ExchangeCandle из ORM ExchangeCandle."""
    return DomainExchangeCandle(
        id=exchange_candle.id,
        dt_unix=int(exchange_candle.timestamp.timestamp() * 1000),
        open=exchange_candle.open,
        high=exchange_candle.high,
        low=exchange_candle.low,
        close=exchange_candle.close,
        volume=exchange_candle.volume,
    )


@pytest.fixture
def domain_signal(domain_candle) -> DomainTraderSignal:
    """Domain TraderSignal (id=None для sync)."""
    return DomainTraderSignal(
        timestamp=domain_candle.timestamp,
        price=domain_candle.close,
        candle=domain_candle,
        type=DomainSignalType.BUY,
        data={"test": True},
    )


@pytest.fixture
def domain_position(domain_trading_pair) -> DomainTraderPosition:
    """Domain TraderPosition с orders."""
    now = datetime.now(UTC)
    buy_order = DomainExchangeClientOrder(
        exchange_order_id="buy-order-001",
        status=DomainOrderStatus.CLOSED,
        type=DomainOrderType.MARKET,
        trading_pair=domain_trading_pair,
        side=DomainOrderSide.BUY,
        timestamp=now,
        amount=Decimal("0.1"),
        price=Decimal("50000.00"),
        cost=Decimal("5000.00"),
        fee=Decimal("5.00"),
    )
    return DomainTraderPosition(
        type=DomainPositionType.LONG,
        status=DomainPositionStatus.OPENED,
        amount=Decimal("0.1"),
        open_price=Decimal("50000.00"),
        stop_loss=Decimal("49000.00"),
        take_profit=Decimal("52000.00"),
        opened_at=now,
        recalculated_at=now,
        total_fee=Decimal("5.00"),
        orders=[buy_order],
    )


@pytest.fixture
def domain_closed_position(domain_trading_pair) -> DomainTraderPosition:
    """Закрытая Domain TraderPosition с orders."""
    now = datetime.now(UTC)
    buy_order = DomainExchangeClientOrder(
        exchange_order_id="buy-order-002",
        status=DomainOrderStatus.CLOSED,
        type=DomainOrderType.MARKET,
        trading_pair=domain_trading_pair,
        side=DomainOrderSide.BUY,
        timestamp=now - timedelta(hours=1),
        amount=Decimal("0.1"),
        price=Decimal("50000.00"),
        cost=Decimal("5000.00"),
        fee=Decimal("5.00"),
    )
    sell_order = DomainExchangeClientOrder(
        exchange_order_id="sell-order-002",
        status=DomainOrderStatus.CLOSED,
        type=DomainOrderType.MARKET,
        trading_pair=domain_trading_pair,
        side=DomainOrderSide.SELL,
        timestamp=now,
        amount=Decimal("0.1"),
        price=Decimal("52000.00"),
        cost=Decimal("5200.00"),
        fee=Decimal("5.20"),
    )
    return DomainTraderPosition(
        type=DomainPositionType.LONG,
        status=DomainPositionStatus.CLOSED,
        amount=Decimal("0.1"),
        open_price=Decimal("50000.00"),
        close_price=Decimal("52000.00"),
        stop_loss=Decimal("49000.00"),
        take_profit=Decimal("52000.00"),
        opened_at=now - timedelta(hours=1),
        closed_at=now,
        recalculated_at=now,
        total_fee=Decimal("10.20"),
        close_reason=DomainPositionCloseReason.TAKE_PROFIT,
        orders=[buy_order, sell_order],
    )


@pytest.fixture
def domain_error() -> DomainTraderError:
    """Domain TraderError (id=None)."""
    return DomainTraderError(
        timestamp=datetime.now(UTC),
        message="Test error message",
        type="TestError",
        traceback="Traceback (most recent call last)...",
    )


@pytest.fixture
def trader_order(trader, closed_trader_position, exchange_client_order) -> TraderOrder:
    """Создает TraderOrder."""
    return TraderOrder.objects.create(
        trader=trader,
        order=exchange_client_order,
        position=closed_trader_position,
    )
