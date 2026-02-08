"""
Фикстуры для тестов traders app.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from candle_sources.models import CandleSource
from core.utils.types import (
    OrderSide,
    OrderStatus,
    PositionCloseReason,
    PositionStatus,
    PositionType,
    SignalType,
    Timeframe,
    TraderStatus,
)
from exchange_clients.domain import ByBitExchangeClient
from exchange_clients.domain.exchange_clients import BinanceExchangeClient
from exchange_clients.models import ExchangeClient, ExchangeClientOrder
from exchanges.models import Exchange, ExchangeCandle, TradingPair
from risk_managers.domain.risk_managers import SLPercentTPPercentPSAllInRiskManager
from risk_managers.models import RiskManager
from strategies.domain.strategies import MoneyFlowIndexStrategy
from strategies.models import ArbitrageStrategy, Strategy
from traders.models import (
    ArbitrageTrader,
    ArbitrageTraderPosition,
    ArbitrageTraderSignal,
    Trader,
    TraderPosition,
    TraderSignal,
)


@pytest.fixture
def exchange() -> Exchange:
    """Создает тестовую биржу."""
    exchange, _ = Exchange.objects.get_or_create(
        class_name=ByBitExchangeClient.__name__,
        defaults={"name": "Bybit Test"},
    )
    return exchange


@pytest.fixture
def second_exchange() -> Exchange:
    """Создает вторую тестовую биржу."""
    exchange, _ = Exchange.objects.get_or_create(
        class_name=BinanceExchangeClient.__name__,
        defaults={"name": "Binance Test"},
    )
    return exchange


@pytest.fixture
def trading_pair() -> TradingPair:
    """Создает тестовую торговую пару."""
    pair, _ = TradingPair.objects.get_or_create(
        name="BTC/USDT",
        defaults={
            "symbol": "BTC/USDT:USDT",
            "min_amount": Decimal("0.001"),
            "max_amount": Decimal("1000"),
            "fee_percent": Decimal("0.1"),
        },
    )
    return pair


@pytest.fixture
def exchange_client(exchange: Exchange) -> ExchangeClient:
    """Создает тестового клиента биржи."""
    return ExchangeClient.objects.create(
        exchange=exchange,
        api_key="test_api_key",
        api_secret="test_api_secret",
        name="Test Client",
        demo=True,
    )


@pytest.fixture
def second_exchange_client(second_exchange: Exchange) -> ExchangeClient:
    """Создает второго клиента биржи для арбитража."""
    return ExchangeClient.objects.create(
        exchange=second_exchange,
        api_key="test_api_key_2",
        api_secret="test_api_secret_2",
        name="Test Client 2",
        demo=True,
    )


@pytest.fixture
def candle_source(
    exchange_client: ExchangeClient, trading_pair: TradingPair
) -> CandleSource:
    """Создает источник свечей."""
    return CandleSource.objects.create(
        exchange_client=exchange_client,
        trading_pair=trading_pair,
        timeframe=Timeframe.ONE_HOUR,
    )


@pytest.fixture
def second_candle_source(
    second_exchange_client: ExchangeClient, trading_pair: TradingPair
) -> CandleSource:
    """Создает второй источник свечей для арбитража."""
    return CandleSource.objects.create(
        exchange_client=second_exchange_client,
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
def arbitrage_strategy() -> ArbitrageStrategy:
    """Создает арбитражную стратегию."""
    return ArbitrageStrategy.objects.create(
        name="Test Arbitrage Strategy",
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
def arbitrage_trader(
    candle_source: CandleSource,
    second_candle_source: CandleSource,
    exchange_client: ExchangeClient,
    second_exchange_client: ExchangeClient,
    arbitrage_strategy: ArbitrageStrategy,
    risk_manager: RiskManager,
) -> ArbitrageTrader:
    """Создает арбитражного трейдера."""
    return ArbitrageTrader.objects.create(
        first_candle_source=candle_source,
        second_candle_source=second_candle_source,
        first_exchange_client=exchange_client,
        second_exchange_client=second_exchange_client,
        strategy=arbitrage_strategy,
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
def second_exchange_candle(
    second_exchange: Exchange, trading_pair: TradingPair
) -> ExchangeCandle:
    """Создает вторую свечу для арбитража."""
    now = datetime.now(UTC)
    return ExchangeCandle.objects.create(
        exchange=second_exchange,
        trading_pair=trading_pair,
        timeframe=Timeframe.ONE_HOUR,
        timestamp=now,
        open=Decimal("50100.00"),
        high=Decimal("51100.00"),
        low=Decimal("49100.00"),
        close=Decimal("50600.00"),
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


@pytest.fixture
def arbitrage_signal(
    arbitrage_trader: ArbitrageTrader,
    exchange_candle: ExchangeCandle,
    second_exchange_candle: ExchangeCandle,
) -> ArbitrageTraderSignal:
    """Создает арбитражный сигнал."""
    return ArbitrageTraderSignal.objects.create(
        trader=arbitrage_trader,
        timestamp=datetime.now(UTC),
        first_price=Decimal("50500.00"),
        second_price=Decimal("50600.00"),
        first_type=SignalType.BUY,
        second_type=SignalType.SELL,
        first_candle=exchange_candle,
        second_candle=second_exchange_candle,
        data={},
    )


@pytest.fixture
def arbitrage_position(arbitrage_trader: ArbitrageTrader) -> ArbitrageTraderPosition:
    """Создает арбитражную позицию."""
    now = datetime.now(UTC)
    return ArbitrageTraderPosition.objects.create(
        trader=arbitrage_trader,
        type=PositionType.LONG,
        first_type=PositionType.LONG,
        second_type=PositionType.SHORT,
        status=PositionStatus.OPENED,
        amount=Decimal("0.1"),
        first_open_price=Decimal("50000.00"),
        second_open_price=Decimal("50100.00"),
        opened_at=now,
        total_fee=Decimal("0.10"),
    )


@pytest.fixture
def closed_arbitrage_position(
    arbitrage_trader: ArbitrageTrader,
) -> ArbitrageTraderPosition:
    """Создает закрытую арбитражную позицию."""
    now = datetime.now(UTC)
    return ArbitrageTraderPosition.objects.create(
        trader=arbitrage_trader,
        type=PositionType.LONG,
        first_type=PositionType.LONG,
        second_type=PositionType.SHORT,
        status=PositionStatus.CLOSED,
        amount=Decimal("0.1"),
        first_open_price=Decimal("50000.00"),
        first_close_price=Decimal("50500.00"),
        second_open_price=Decimal("50100.00"),
        second_close_price=Decimal("49800.00"),
        opened_at=now - timedelta(hours=1),
        closed_at=now,
        total_fee=Decimal("0.20"),
        close_reason=PositionCloseReason.STRATEGY,
    )
