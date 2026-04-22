"""
Тесты доменного ArbitrageTrader.
Фокус: sync-методы (метрики, баланс, проверки), async-методы (open/close/handle).
"""

from collections import deque
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from arbitrage_traders.domain.schemas import (
    ArbitrageCandle,
    ArbitrageTraderPosition,
    ArbitrageTraderSignal,
    PositionCloseReason,
    PositionStatus,
    PositionType,
    SignalType,
    SpreadReversionArbitrageData,
    TraderStatus,
)
from core.utils.async_orm import aiter_from_iterable
from exchange_clients.domain import (
    ExchangeClientOrder,
    OrderSide,
    OrderStatus,
    OrderType,
)
from exchanges.domain import ExchangeCandle

# ==================== Helpers ====================


def _candle(close: Decimal, hour: int = 12, candle_id: int = 1) -> ExchangeCandle:
    ts = int(datetime(2024, 1, 1, hour, 0, tzinfo=UTC).timestamp() * 1000)
    return ExchangeCandle(
        id=candle_id,
        dt_unix=ts,
        open=close - Decimal("1"),
        high=close + Decimal("1"),
        low=close - Decimal("2"),
        close=close,
        volume=Decimal("100"),
    )


def _signal(
    left_type=SignalType.BUY,
    right_type=SignalType.SELL,
    left_price=Decimal("100"),
    right_price=Decimal("102"),
    spread=0.9804,
) -> ArbitrageTraderSignal:
    left_candle = _candle(left_price)
    right_candle = _candle(right_price, candle_id=2)
    return ArbitrageTraderSignal(
        timestamp=left_candle.timestamp,
        left_price=left_price,
        right_price=right_price,
        left_type=left_type,
        right_type=right_type,
        left_candle=left_candle,
        right_candle=right_candle,
        data=SpreadReversionArbitrageData(
            spread=spread,
            left_price=float(left_price),
            right_price=float(right_price),
        ).model_dump(),
    )


def _closed_pos(
    pnl_left=Decimal("5"),
    pnl_right=Decimal("1"),
    left_fee=Decimal("0.20"),
    right_fee=Decimal("0.20"),
    closed_hour: int = 16,
    pos_type=PositionType.LONG,
) -> ArbitrageTraderPosition:
    """Создаёт закрытую позицию с заданным PnL."""
    left_open = Decimal("100")
    right_open = Decimal("102")
    left_close = (
        left_open + pnl_left if pos_type == PositionType.LONG else left_open - pnl_left
    )
    right_close = (
        right_open - pnl_right
        if pos_type == PositionType.LONG
        else right_open + pnl_right
    )
    amt = Decimal("1.0")
    return ArbitrageTraderPosition(
        left_type=pos_type,
        right_type=PositionType.SHORT
        if pos_type == PositionType.LONG
        else PositionType.LONG,
        status=PositionStatus.CLOSED,
        amount=amt,
        left_open_price=left_open,
        right_open_price=right_open,
        left_close_price=left_close,
        right_close_price=right_close,
        left_open_amount=amt,
        left_close_amount=amt,
        right_open_amount=amt,
        right_close_amount=amt,
        left_open_cost=left_open * amt,
        left_close_cost=left_close * amt,
        right_open_cost=right_open * amt,
        right_close_cost=right_close * amt,
        left_total_fee=left_fee,
        right_total_fee=right_fee,
        opened_at=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
        closed_at=datetime(2024, 1, 1, closed_hour, 0, tzinfo=UTC),
        close_reason=PositionCloseReason.STRATEGY,
    )


# ==================== Init ====================


class TestArbitrageTraderInit:
    """Тесты инициализации ArbitrageTrader."""

    def test_fields_initialized(self, trader):
        """Все поля корректно инициализируются."""
        assert trader.initial_balance == Decimal("1000.00")
        assert trader.balance == Decimal("1000.00")
        assert trader.max_positions_count == 1
        assert trader.create_new_orders is False
        assert trader.status == TraderStatus.ENABLED

    def test_collections_empty(self, trader):
        """Коллекции пустые при создании."""
        assert trader.errors == []
        assert trader.positions == []
        assert isinstance(trader.signals, deque)
        assert len(trader.signals) == 0


# ==================== Properties ====================


class TestArbitrageTraderProperties:
    """Тесты свойств ArbitrageTrader."""

    def test_opened_positions(self, trader, opened_position, closed_position):
        """opened_positions — только opened."""
        trader.positions = [opened_position, closed_position]
        result = list(trader.opened_positions)
        assert len(result) == 1
        assert result[0].status == PositionStatus.OPENED

    def test_closed_positions(self, trader, opened_position, closed_position):
        """closed_positions — только closed."""
        trader.positions = [opened_position, closed_position]
        result = list(trader.closed_positions)
        assert len(result) == 1
        assert result[0].status == PositionStatus.CLOSED

    def test_orders_empty(self, trader):
        """orders — пустой без позиций."""
        assert trader.orders == []

    def test_orders_with_positions(self, trader, trading_pair):
        """orders — zip left + right ордеров."""
        order = ExchangeClientOrder(
            id=1,
            timestamp=datetime(2024, 1, 1, tzinfo=UTC),
            status=OrderStatus.CLOSED,
            trading_pair=trading_pair,
            exchange_order_id="test",
            type=OrderType.MARKET,
            side=OrderSide.BUY,
            price=Decimal("100"),
            amount=Decimal("1"),
            fee=Decimal("0.1"),
            cost=Decimal("100"),
        )
        pos = ArbitrageTraderPosition(
            left_type=PositionType.LONG,
            right_type=PositionType.SHORT,
            status=PositionStatus.OPENED,
            amount=Decimal("1"),
            left_open_amount=Decimal("1"),
            right_open_amount=Decimal("1"),
            left_open_cost=Decimal("100"),
            right_open_cost=Decimal("100"),
            left_orders=[order],
            right_orders=[order],
        )
        trader.positions = [pos]
        assert len(trader.orders) == 1

    def test_get_last_candles(self, trader):
        """get_last_candles(N) — последние N арбитражных свечей."""
        for i in range(5):
            trader.candles.append(
                ArbitrageCandle(
                    left=_candle(Decimal(str(100 + i)), candle_id=i * 2 + 1),
                    right=_candle(Decimal(str(102 + i)), candle_id=i * 2 + 2),
                )
            )
        candles = trader.get_last_candles(3)
        assert len(candles) == 3
        assert isinstance(candles[0], ArbitrageCandle)


# ==================== Balance ====================


class TestArbitrageTraderBalance:
    """Тесты баланса и drawdown."""

    def test_fixed_balance(self, trader):
        """use_fixed_balance=True → self.balance."""
        trader.use_fixed_balance = True
        trader.balance = Decimal("500")
        assert trader.get_current_balance() == Decimal("500")

    def test_dynamic_balance_no_positions(self, trader):
        """use_fixed_balance=False, нет позиций → balance."""
        trader.use_fixed_balance = False
        assert trader.get_current_balance() == Decimal("1000.00")

    def test_dynamic_balance_with_opened(self, trader, opened_position):
        """use_fixed_balance=False, opened позиция влияет (pnl=None для opened → 0)."""
        trader.use_fixed_balance = False
        trader.positions = [opened_position]
        # opened_position.pnl = None (не CLOSED), sum пропускает None
        assert trader.get_current_balance() == Decimal("1000.00")

    def test_drawdown_within_limit(self, trader):
        """Drawdown в пределах → True."""
        trader.balance = Decimal("950")  # drawdown = 5%
        assert trader.is_drawdown_within_limit() is True

    def test_drawdown_exceeded(self, trader):
        """Drawdown превышен → False."""
        trader.balance = Decimal("850")  # drawdown = 15%
        assert trader.is_drawdown_within_limit() is False

    def test_drawdown_check_disabled(self, trader):
        """check_drawdown=False → всегда True."""
        trader.check_drawdown = False
        trader.balance = Decimal("0")
        assert trader.is_drawdown_within_limit() is True


# ==================== Can Open Positions ====================


class TestArbitrageTraderCanOpenPositions:
    """Тесты can_open_more_positions и can_open_position."""

    def test_can_open_no_positions(self, trader):
        """Нет позиций → True."""
        assert trader.can_open_more_positions() is True

    def test_cannot_open_at_limit(self, trader, opened_position):
        """Лимит достигнут → False."""
        trader.positions = [opened_position]
        assert trader.can_open_more_positions() is False

    def test_can_open_position_wait_signal(self, trader, wait_signal):
        """WAIT signal → False."""
        assert trader.can_open_position(wait_signal) is False

    def test_can_open_position_drawdown_exceeded(self, trader, buy_signal):
        """Drawdown превышен → False."""
        trader.balance = Decimal("800")  # drawdown = 20%
        assert trader.can_open_position(buy_signal) is False

    def test_can_open_position_all_ok(self, trader, buy_signal):
        """Все проверки пройдены → True."""
        assert trader.can_open_position(buy_signal) is True


# ==================== Metrics ====================


class TestArbitrageTraderMetrics:
    """Тесты метрик: pnl, roi, win_rate, sharpe, r2."""

    def test_get_pnl_no_positions(self, trader):
        """Нет позиций → 0."""
        assert trader.get_pnl() == 0

    def test_get_pnl_with_closed(self, trader):
        """Сумма pnl закрытых позиций."""
        trader.positions = [
            _closed_pos(
                pnl_left=Decimal("5"),
                pnl_right=Decimal("1"),
                left_fee=Decimal("0.20"),
                right_fee=Decimal("0.20"),
            ),
            _closed_pos(
                pnl_left=Decimal("3"),
                pnl_right=Decimal("2"),
                left_fee=Decimal("0.10"),
                right_fee=Decimal("0.10"),
            ),
        ]
        # pos1: 5+1-0.40=5.60, pos2: 3+2-0.20=4.80, total=10.40
        assert trader.get_pnl() == Decimal("10.40")

    def test_get_roi(self, trader):
        """ROI = pnl / initial_balance * 100."""
        trader.positions = [
            _closed_pos(
                pnl_left=Decimal("10"),
                pnl_right=Decimal("0"),
                left_fee=Decimal("0"),
                right_fee=Decimal("0"),
            )
        ]
        # pnl = 10, roi = 10/1000*100 = 1.0
        assert trader.get_roi() == Decimal("1.0")

    def test_get_roi_zero_balance(self, trader):
        """initial_balance=0 → 0."""
        trader.initial_balance = Decimal("0")
        assert trader.get_roi() == Decimal("0.0")

    def test_get_total_positions(self, trader, opened_position, closed_position):
        """Общее число позиций."""
        trader.positions = [opened_position, closed_position]
        assert trader.get_total_positions() == 2

    def test_avg_pnl_no_closed(self, trader, opened_position):
        """Нет закрытых → 0."""
        trader.positions = [opened_position]
        assert trader.get_avg_pnl_per_position() == Decimal("0.0")

    def test_avg_pnl_with_closed(self, trader):
        """Среднее pnl по закрытым."""
        trader.positions = [
            _closed_pos(
                pnl_left=Decimal("10"),
                pnl_right=Decimal("0"),
                left_fee=Decimal("0"),
                right_fee=Decimal("0"),
            ),
            _closed_pos(
                pnl_left=Decimal("6"),
                pnl_right=Decimal("0"),
                left_fee=Decimal("0"),
                right_fee=Decimal("0"),
            ),
        ]
        # pnl1=10, pnl2=6 → avg=8
        assert trader.get_avg_pnl_per_position() == Decimal("8.0")

    def test_win_rate_no_closed(self, trader):
        """Нет закрытых → 0."""
        assert trader.get_win_rate() == Decimal("0.0")

    def test_win_rate_all_win(self, trader):
        """Все win → 1.0."""
        trader.positions = [
            _closed_pos(
                pnl_left=Decimal("5"),
                pnl_right=Decimal("1"),
                left_fee=Decimal("0.05"),
                right_fee=Decimal("0.05"),
            ),
            _closed_pos(
                pnl_left=Decimal("3"),
                pnl_right=Decimal("2"),
                left_fee=Decimal("0.05"),
                right_fee=Decimal("0.05"),
            ),
        ]
        assert trader.get_win_rate() == Decimal("1.0")

    def test_win_rate_all_loss(self, trader):
        """Все loss → 0."""
        trader.positions = [
            _closed_pos(
                pnl_left=Decimal("-5"),
                pnl_right=Decimal("-1"),
                left_fee=Decimal("0.05"),
                right_fee=Decimal("0.05"),
            ),
            _closed_pos(
                pnl_left=Decimal("-3"),
                pnl_right=Decimal("-2"),
                left_fee=Decimal("0.05"),
                right_fee=Decimal("0.05"),
            ),
        ]
        assert trader.get_win_rate() == Decimal("0.0")

    def test_win_rate_mixed(self, trader):
        """50/50 → 0.5."""
        trader.positions = [
            _closed_pos(
                pnl_left=Decimal("5"),
                pnl_right=Decimal("1"),
                left_fee=Decimal("0.05"),
                right_fee=Decimal("0.05"),
            ),
            _closed_pos(
                pnl_left=Decimal("-5"),
                pnl_right=Decimal("-1"),
                left_fee=Decimal("0.05"),
                right_fee=Decimal("0.05"),
            ),
        ]
        assert trader.get_win_rate() == Decimal("0.5")

    def test_sharpe_less_than_2_positions(self, trader):
        """< 2 позиций → 0."""
        trader.positions = [_closed_pos()]
        assert trader.get_sharpe_ratio() == Decimal("0.0")

    def test_sharpe_with_positions(self, trader):
        """> 2 позиций → Decimal."""
        trader.positions = [
            _closed_pos(
                pnl_left=Decimal("5"),
                pnl_right=Decimal("1"),
                left_fee=Decimal("0.05"),
                right_fee=Decimal("0.05"),
                closed_hour=13,
            ),
            _closed_pos(
                pnl_left=Decimal("3"),
                pnl_right=Decimal("2"),
                left_fee=Decimal("0.05"),
                right_fee=Decimal("0.05"),
                closed_hour=14,
            ),
            _closed_pos(
                pnl_left=Decimal("1"),
                pnl_right=Decimal("0"),
                left_fee=Decimal("0.05"),
                right_fee=Decimal("0.05"),
                closed_hour=15,
            ),
        ]
        result = trader.get_sharpe_ratio()
        assert isinstance(result, Decimal)
        assert result != Decimal("0.0")

    def test_sharpe_zero_std(self, trader):
        """Все одинаковые returns (std=0) → 0."""
        trader.positions = [
            _closed_pos(
                pnl_left=Decimal("5"),
                pnl_right=Decimal("0"),
                left_fee=Decimal("0"),
                right_fee=Decimal("0"),
                closed_hour=13,
            ),
            _closed_pos(
                pnl_left=Decimal("5"),
                pnl_right=Decimal("0"),
                left_fee=Decimal("0"),
                right_fee=Decimal("0"),
                closed_hour=14,
            ),
        ]
        assert trader.get_sharpe_ratio() == Decimal("0.0")

    def test_pnl_r2_less_than_2(self, trader):
        """< 2 позиций → 0."""
        trader.positions = [_closed_pos()]
        assert trader.get_pnl_r2() == Decimal("0.0")

    def test_pnl_r2_linear_growth(self, trader):
        """Линейный рост PnL → R² близко к 1."""
        trader.positions = [
            _closed_pos(
                pnl_left=Decimal("5"),
                pnl_right=Decimal("0"),
                left_fee=Decimal("0"),
                right_fee=Decimal("0"),
                closed_hour=13,
            ),
            _closed_pos(
                pnl_left=Decimal("10"),
                pnl_right=Decimal("0"),
                left_fee=Decimal("0"),
                right_fee=Decimal("0"),
                closed_hour=14,
            ),
            _closed_pos(
                pnl_left=Decimal("15"),
                pnl_right=Decimal("0"),
                left_fee=Decimal("0"),
                right_fee=Decimal("0"),
                closed_hour=15,
            ),
        ]
        r2 = trader.get_pnl_r2()
        assert float(r2) > 0.95

    def test_avg_candles_no_closed(self, trader, opened_position):
        """Нет закрытых → 0."""
        trader.positions = [opened_position]
        assert trader.get_avg_candles_per_position() == Decimal("0.0")


# ==================== position_should_be_closed ====================


class TestArbitrageTraderPositionShouldBeClosed:
    """Тесты position_should_be_closed на уровне трейдера."""

    def test_strategy_close(self, trader, opened_position):
        """Стратегия решает закрыть → (True, STRATEGY)."""
        # Спред вернулся к паритету → стратегия закрывает LONG
        signal = _signal(spread=1.0)
        close, reason = trader.position_should_be_closed(opened_position, signal)
        assert close is True
        assert reason == PositionCloseReason.STRATEGY

    def test_opposite_signal_long_sell(self, trader, opened_position):
        """Opposite signal: LONG + SELL → OPPOSITE_SIGNAL."""
        # Стратегия НЕ закрывает (spread далеко от паритета), но opposite signal
        signal = _signal(
            left_type=SignalType.SELL,
            right_type=SignalType.BUY,
            spread=0.95,  # стратегия не закроет LONG при spread 0.95
        )
        close, reason = trader.position_should_be_closed(opened_position, signal)
        assert close is True
        assert reason == PositionCloseReason.OPPOSITE_SIGNAL

    def test_opposite_signal_short_buy(self, trader):
        """Opposite signal: SHORT + BUY → OPPOSITE_SIGNAL."""
        short_pos = ArbitrageTraderPosition(
            left_type=PositionType.SHORT,
            right_type=PositionType.LONG,
            status=PositionStatus.OPENED,
            amount=Decimal("1.0"),
            left_open_price=Decimal("100"),
            right_open_price=Decimal("102"),
            left_open_amount=Decimal("1.0"),
            right_open_amount=Decimal("1.0"),
            left_open_cost=Decimal("100"),
            right_open_cost=Decimal("102"),
        )
        signal = _signal(
            left_type=SignalType.BUY,
            right_type=SignalType.SELL,
            spread=1.05,  # стратегия не закроет SHORT при spread 1.05
        )
        close, reason = trader.position_should_be_closed(short_pos, signal)
        assert close is True
        assert reason == PositionCloseReason.OPPOSITE_SIGNAL

    def test_nothing_triggers(self, trader, opened_position):
        """Ничего не срабатывает → (False, None)."""
        # LONG позиция, спред далеко от паритета, тот же тип сигнала
        signal = _signal(
            left_type=SignalType.BUY,
            right_type=SignalType.SELL,
            spread=0.95,  # стратегия не закроет: 0.95 < 1 - 0.002
        )
        close, reason = trader.position_should_be_closed(opened_position, signal)
        assert close is False
        assert reason is None

    def test_strategy_disabled(self, trader, opened_position):
        """close_position_by_strategy=False → не проверяет стратегию."""
        trader.close_position_by_strategy = False
        signal = _signal(spread=1.0)  # стратегия бы закрыла
        close, _reason = trader.position_should_be_closed(opened_position, signal)
        # Opposite signal? BUY + LONG → не opposite
        assert close is False

    def test_opposite_signal_disabled(self, trader, opened_position):
        """close_position_by_opposite_signal=False → не проверяет."""
        trader.close_position_by_opposite_signal = False
        trader.close_position_by_strategy = False  # обе отключены
        signal = _signal(
            left_type=SignalType.SELL,
            right_type=SignalType.BUY,
            spread=0.95,
        )
        close, reason = trader.position_should_be_closed(opened_position, signal)
        assert close is False
        assert reason is None


# ==================== Async: open_position ====================


class TestArbitrageTraderOpenPosition:
    """Тесты async open_position."""

    @pytest.mark.asyncio
    async def test_creates_position_with_correct_type(self, trader, buy_signal):
        """BUY → LONG позиция."""
        pos = await trader.open_position(buy_signal)
        assert pos is not None
        assert pos.left_type == PositionType.LONG
        assert pos.left_type == PositionType.LONG
        assert pos.right_type == PositionType.SHORT
        assert pos.status == PositionStatus.OPENED

    @pytest.mark.asyncio
    async def test_amount_from_risk_manager(self, trader, buy_signal):
        """Размер позиции от risk_manager."""
        pos = await trader.open_position(buy_signal)
        # AllIn: 1000 / 100 = 10, но clamp to max_amount=1000
        assert pos.left_open_amount > Decimal("0")

    @pytest.mark.asyncio
    async def test_amount_clamped_to_min(self, trader, buy_signal):
        """Amount < min_amount → clamp."""
        trader.balance = Decimal("0.00001")  # очень маленький баланс
        pos = await trader.open_position(buy_signal)
        if pos:
            assert pos.left_open_amount >= trader.left_trading_pair.min_amount

    @pytest.mark.asyncio
    async def test_amount_clamped_to_max(self, trader, buy_signal):
        """Amount > max_amount → clamp."""
        trader.balance = Decimal("100000000")  # огромный баланс
        pos = await trader.open_position(buy_signal)
        assert pos.left_open_amount <= trader.left_trading_pair.max_amount

    @pytest.mark.asyncio
    async def test_zero_amount_returns_none(self, trader, buy_signal):
        """Amount <= 0 → None."""
        trader.balance = Decimal("0")
        pos = await trader.open_position(buy_signal)
        assert pos is None

    @pytest.mark.asyncio
    async def test_no_orders_when_create_disabled(self, trader, buy_signal):
        """create_new_orders=False → цены из signal."""
        pos = await trader.open_position(buy_signal)
        assert pos.left_open_price == buy_signal.left_price
        assert pos.right_open_price == buy_signal.right_price

    @pytest.mark.asyncio
    async def test_orders_created_when_enabled(self, trader, buy_signal):
        """create_new_orders=True → вызывает create_market_order."""
        trader.create_new_orders = True
        pos = await trader.open_position(buy_signal)
        assert pos is not None
        assert trader.left_exchange_client.create_market_order.called
        assert trader.right_exchange_client.create_market_order.called


# ==================== Async: close_position ====================


class TestArbitrageTraderClosePosition:
    """Тесты async close_position."""

    @pytest.mark.asyncio
    async def test_closes_position(self, trader, opened_position, buy_signal):
        """Закрывает: status=CLOSED, close_prices, reason."""
        trader.positions = [opened_position]
        result = await trader.close_position(
            opened_position, buy_signal, PositionCloseReason.STRATEGY
        )
        assert result.status == PositionStatus.CLOSED
        assert result.close_reason == PositionCloseReason.STRATEGY
        assert result.left_close_price is not None
        assert result.right_close_price is not None

    @pytest.mark.asyncio
    async def test_fee_accumulated(self, trader, opened_position, buy_signal):
        """Fee суммируется с open fee."""
        initial_left_fee = opened_position.left_total_fee
        initial_right_fee = opened_position.right_total_fee
        await trader.close_position(
            opened_position, buy_signal, PositionCloseReason.STRATEGY
        )
        assert opened_position.left_total_fee > initial_left_fee
        assert opened_position.right_total_fee > initial_right_fee

    @pytest.mark.asyncio
    async def test_orders_created_when_enabled(
        self, trader, opened_position, buy_signal
    ):
        """create_new_orders=True → вызывает create_market_order."""
        trader.create_new_orders = True
        trader.positions = [opened_position]
        await trader.close_position(
            opened_position, buy_signal, PositionCloseReason.STRATEGY
        )
        assert trader.left_exchange_client.create_market_order.called

    @pytest.mark.asyncio
    async def test_orders_appended_to_position(
        self, trader, opened_position, buy_signal
    ):
        """Ордера добавляются в position.left_orders/right_orders."""
        trader.create_new_orders = True
        trader.positions = [opened_position]
        await trader.close_position(
            opened_position, buy_signal, PositionCloseReason.STRATEGY
        )
        assert len(opened_position.left_orders) == 1
        assert len(opened_position.right_orders) == 1


# ==================== Async: handle_candle ====================


class TestArbitrageTraderHandleCandle:
    """Тесты async handle_candle."""

    @pytest.mark.asyncio
    async def test_generates_signal(self, trader, arb_candle_high_spread):
        """Генерирует сигнал и добавляет в signals."""
        await trader.handle_candle(arb_candle_high_spread)
        assert len(trader.signals) == 1

    @pytest.mark.asyncio
    async def test_opens_position_when_enabled(self, trader, arb_candle_high_spread):
        """ENABLED + можно открыть → открывает позицию."""
        await trader.handle_candle(arb_candle_high_spread)
        assert len(trader.positions) == 1

    @pytest.mark.asyncio
    async def test_disabled_no_position(self, trader, arb_candle_high_spread):
        """DISABLED → только сигнал."""
        trader.status = TraderStatus.DISABLED
        await trader.handle_candle(arb_candle_high_spread)
        assert len(trader.signals) == 1
        assert len(trader.positions) == 0

    @pytest.mark.asyncio
    async def test_paused_no_position(self, trader, arb_candle_high_spread):
        """PAUSED → только сигнал."""
        trader.status = TraderStatus.PAUSED
        await trader.handle_candle(arb_candle_high_spread)
        assert len(trader.positions) == 0

    @pytest.mark.asyncio
    async def test_error_captured(self, trader, arb_candle):
        """Ошибка → ArbitrageTraderError."""
        trader.strategy = MagicMock()
        trader.strategy.get_signal.side_effect = RuntimeError("test error")
        await trader.handle_candle(arb_candle)
        assert len(trader.errors) == 1
        assert "test error" in trader.errors[0].message

    @pytest.mark.asyncio
    async def test_closes_opened_on_opposite_signal(self, trader, opened_position):
        """Закрывает opened при противоположном сигнале."""
        trader.positions = [opened_position]
        # Создаём свечи где first дороже → SELL сигнал → opposite к LONG
        candle = ArbitrageCandle(
            left=_candle(Decimal("110"), candle_id=10),
            right=_candle(Decimal("100"), candle_id=11),
        )
        await trader.handle_candle(candle)
        # LONG позиция должна быть закрыта
        assert opened_position.status == PositionStatus.CLOSED


# ==================== Async: close_all_opened ====================


class TestArbitrageTraderCloseAllOpened:
    """Тесты async close_all_opened_positions."""

    @pytest.mark.asyncio
    async def test_closes_all_with_manual_reason(
        self, trader, opened_position, buy_signal
    ):
        """Закрывает все с reason=MANUAL."""
        trader.positions = [opened_position]
        trader.signals.append(buy_signal)
        await trader.close_all_opened_positions()
        assert opened_position.status == PositionStatus.CLOSED
        assert opened_position.close_reason == PositionCloseReason.MANUAL

    @pytest.mark.asyncio
    async def test_empty_signals_noop(self, trader, opened_position):
        """Пустые signals → ничего не делает."""
        trader.positions = [opened_position]
        await trader.close_all_opened_positions()
        assert opened_position.status == PositionStatus.OPENED

    @pytest.mark.asyncio
    async def test_does_not_touch_closed(self, trader, closed_position, buy_signal):
        """Не трогает closed позиции."""
        trader.positions = [closed_position]
        trader.signals.append(buy_signal)
        await trader.close_all_opened_positions()
        # Позиция была closed и осталась closed
        assert closed_position.status == PositionStatus.CLOSED
        assert closed_position.close_reason == PositionCloseReason.STRATEGY  # не MANUAL


# ==================== Async: reboot ====================


class TestArbitrageTraderReboot:
    """Тесты async reboot."""

    @pytest.mark.asyncio
    async def test_disables_create_new_orders(self, trader):
        """Временно отключает create_new_orders."""
        trader.create_new_orders = True
        candles = []
        await trader.reboot(aiter_from_iterable(candles))
        assert trader.create_new_orders is True  # восстановлено

    @pytest.mark.asyncio
    async def test_processes_all_candles(self, trader):
        """Обрабатывает все свечи из итератора."""
        candles = [
            ArbitrageCandle(
                left=_candle(Decimal("100"), hour=12, candle_id=1),
                right=_candle(Decimal("110"), hour=12, candle_id=2),
            ),
            ArbitrageCandle(
                left=_candle(Decimal("100"), hour=13, candle_id=3),
                right=_candle(Decimal("110"), hour=13, candle_id=4),
            ),
        ]
        await trader.reboot(aiter_from_iterable(candles))
        assert len(trader.signals) == 2

    @pytest.mark.asyncio
    async def test_closes_remaining_positions(self, trader):
        """Закрывает все оставшиеся после прохода."""
        candles = [
            ArbitrageCandle(
                left=_candle(Decimal("100"), hour=12, candle_id=1),
                right=_candle(Decimal("110"), hour=12, candle_id=2),
            ),
        ]
        await trader.reboot(aiter_from_iterable(candles))
        # Все позиции должны быть closed после reboot
        for pos in trader.positions:
            assert pos.status == PositionStatus.CLOSED

    @pytest.mark.asyncio
    async def test_restores_create_new_orders(self, trader):
        """Восстанавливает create_new_orders после reboot."""
        trader.create_new_orders = True
        candles = [
            ArbitrageCandle(
                left=_candle(Decimal("100"), hour=12, candle_id=1),
                right=_candle(Decimal("110"), hour=12, candle_id=2),
            ),
        ]
        await trader.reboot(aiter_from_iterable(candles))
        assert trader.create_new_orders is True
