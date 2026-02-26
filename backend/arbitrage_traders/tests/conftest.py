"""
Фикстуры для тестов arbitrage_traders app.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from arbitrage_traders.domain.risk_managers import PSAllInArbitrageRiskManager
from arbitrage_traders.domain.strategies import SpreadReversionArbitrageStrategy
from arbitrage_traders.models import (
    ArbitrageRiskManager,
    ArbitrageStrategy,
    ArbitrageTrader,
    ArbitrageTraderOrder,
    ArbitrageTraderPosition,
    ArbitrageTraderSignal,
)
from arbitrage_traders.schemas import (
    ArbitragePositionCloseReason,
    ArbitragePositionStatus,
    ArbitragePositionType,
    ArbitrageSignalType,
    ArbitrageTraderStatus,
)
from candle_sources.models import CandleSource
from exchange_clients.domain import ByBitExchangeClient
from exchange_clients.domain.exchange_clients import BinanceExchangeClient
from exchange_clients.models import ExchangeClient
from exchange_clients.models import ExchangeClientOrder as ExchangeClientOrderModel
from exchange_clients.schemas import OrderSide, OrderStatus
from exchanges.models import Exchange, ExchangeCandle, TradingPair
from exchanges.schemas import Timeframe


@pytest.fixture
def exchange() -> Exchange:
    """Создает тестовую биржу."""
    exchange, _ = Exchange.objects.get_or_create(
        class_name=ByBitExchangeClient.__name__,
        defaults={"name": "Bybit Test"},
    )
    return exchange


@pytest.fixture
def right_exchange() -> Exchange:
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
def right_exchange_client(right_exchange: Exchange) -> ExchangeClient:
    """Создает второго клиента биржи для арбитража."""
    return ExchangeClient.objects.create(
        exchange=right_exchange,
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
def right_candle_source(
    right_exchange_client: ExchangeClient, trading_pair: TradingPair
) -> CandleSource:
    """Создает второй источник свечей для арбитража."""
    return CandleSource.objects.create(
        exchange_client=right_exchange_client,
        trading_pair=trading_pair,
        timeframe=Timeframe.ONE_HOUR,
    )


@pytest.fixture
def _candle_timestamp() -> datetime:
    """Общий timestamp для пары свечей."""
    return datetime.now(UTC)


@pytest.fixture
def exchange_candle(
    exchange: Exchange, trading_pair: TradingPair, _candle_timestamp: datetime
) -> ExchangeCandle:
    """Создает свечу биржи."""
    return ExchangeCandle.objects.create(
        exchange=exchange,
        trading_pair=trading_pair,
        timeframe=Timeframe.ONE_HOUR,
        timestamp=_candle_timestamp,
        open=Decimal("50000.00"),
        high=Decimal("51000.00"),
        low=Decimal("49000.00"),
        close=Decimal("50500.00"),
        volume=Decimal("100.00"),
    )


@pytest.fixture
def right_exchange_candle(
    right_exchange: Exchange, trading_pair: TradingPair, _candle_timestamp: datetime
) -> ExchangeCandle:
    """Создает вторую свечу для арбитража."""
    return ExchangeCandle.objects.create(
        exchange=right_exchange,
        trading_pair=trading_pair,
        timeframe=Timeframe.ONE_HOUR,
        timestamp=_candle_timestamp,
        open=Decimal("50100.00"),
        high=Decimal("51100.00"),
        low=Decimal("49100.00"),
        close=Decimal("50600.00"),
        volume=Decimal("100.00"),
    )


@pytest.fixture
def arbitrage_strategy() -> ArbitrageStrategy:
    """Создает арбитражную стратегию."""
    return ArbitrageStrategy.objects.create(
        name="Test Arbitrage Strategy",
        class_name=SpreadReversionArbitrageStrategy.__name__,
        arguments={"open_threshold": 1.0, "close_threshold": 0.2},
    )


@pytest.fixture
def arbitrage_risk_manager() -> ArbitrageRiskManager:
    """Создает арбитражный риск-менеджер."""
    return ArbitrageRiskManager.objects.create(
        name="Test Arbitrage Risk Manager",
        class_name=PSAllInArbitrageRiskManager.__name__,
    )


@pytest.fixture
def arbitrage_trader(
    candle_source: CandleSource,
    right_candle_source: CandleSource,
    exchange_client: ExchangeClient,
    right_exchange_client: ExchangeClient,
    arbitrage_strategy: ArbitrageStrategy,
    arbitrage_risk_manager: ArbitrageRiskManager,
) -> ArbitrageTrader:
    """Создает арбитражного трейдера."""
    return ArbitrageTrader.objects.create(
        left_candle_source=candle_source,
        right_candle_source=right_candle_source,
        left_exchange_client=exchange_client,
        right_exchange_client=right_exchange_client,
        strategy=arbitrage_strategy,
        risk_manager=arbitrage_risk_manager,
        initial_balance=Decimal("1000.00"),
        status=ArbitrageTraderStatus.ENABLED,
    )


@pytest.fixture
def arbitrage_signal(
    arbitrage_trader: ArbitrageTrader,
    exchange_candle: ExchangeCandle,
    right_exchange_candle: ExchangeCandle,
) -> ArbitrageTraderSignal:
    """Создает арбитражный сигнал."""
    return ArbitrageTraderSignal.objects.create(
        trader=arbitrage_trader,
        timestamp=datetime.now(UTC),
        left_price=Decimal("50500.00"),
        right_price=Decimal("50600.00"),
        left_type=ArbitrageSignalType.BUY,
        right_type=ArbitrageSignalType.SELL,
        left_candle=exchange_candle,
        right_candle=right_exchange_candle,
        data={},
    )


@pytest.fixture
def arbitrage_position(arbitrage_trader: ArbitrageTrader) -> ArbitrageTraderPosition:
    """Создает арбитражную позицию."""
    now = datetime.now(UTC)
    return ArbitrageTraderPosition.objects.create(
        trader=arbitrage_trader,
        type=ArbitragePositionType.LONG,
        left_type=ArbitragePositionType.LONG,
        right_type=ArbitragePositionType.SHORT,
        status=ArbitragePositionStatus.OPENED,
        amount=Decimal("0.1"),
        left_open_price=Decimal("50000.00"),
        right_open_price=Decimal("50100.00"),
        opened_at=now,
        left_total_fee=Decimal("0.05"),
        right_total_fee=Decimal("0.05"),
    )


@pytest.fixture
def closed_arbitrage_position(
    arbitrage_trader: ArbitrageTrader,
) -> ArbitrageTraderPosition:
    """Создает закрытую арбитражную позицию."""
    now = datetime.now(UTC)
    return ArbitrageTraderPosition.objects.create(
        trader=arbitrage_trader,
        type=ArbitragePositionType.LONG,
        left_type=ArbitragePositionType.LONG,
        right_type=ArbitragePositionType.SHORT,
        status=ArbitragePositionStatus.CLOSED,
        amount=Decimal("0.1"),
        left_open_price=Decimal("50000.00"),
        left_close_price=Decimal("50500.00"),
        right_open_price=Decimal("50100.00"),
        right_close_price=Decimal("49800.00"),
        opened_at=now - timedelta(hours=1),
        closed_at=now,
        left_total_fee=Decimal("0.10"),
        right_total_fee=Decimal("0.10"),
        close_reason=ArbitragePositionCloseReason.STRATEGY,
    )


@pytest.fixture
def arbitrage_order(
    arbitrage_trader: ArbitrageTrader,
    closed_arbitrage_position: ArbitrageTraderPosition,
    trading_pair: TradingPair,
) -> ArbitrageTraderOrder:
    """Создает арбитражный ордер с двумя ExchangeClientOrder."""
    now = datetime.now(UTC)
    left_ec_order = ExchangeClientOrderModel.objects.create(
        exchange_client=arbitrage_trader.left_exchange_client,
        exchange_order_id="left-order-001",
        status=OrderStatus.CLOSED,
        side=OrderSide.BUY,
        timestamp=now - timedelta(hours=1),
        trading_pair=trading_pair,
        price=Decimal("50000.00"),
        amount=Decimal("0.1"),
        cost=Decimal("5000.00"),
        fee=Decimal("5.00"),
    )
    right_ec_order = ExchangeClientOrderModel.objects.create(
        exchange_client=arbitrage_trader.right_exchange_client,
        exchange_order_id="right-order-001",
        status=OrderStatus.CLOSED,
        side=OrderSide.SELL,
        timestamp=now - timedelta(hours=1),
        trading_pair=trading_pair,
        price=Decimal("50100.00"),
        amount=Decimal("0.1"),
        cost=Decimal("5010.00"),
        fee=Decimal("5.01"),
    )
    return ArbitrageTraderOrder.objects.create(
        trader=arbitrage_trader,
        left_order=left_ec_order,
        right_order=right_ec_order,
        position=closed_arbitrage_position,
    )
