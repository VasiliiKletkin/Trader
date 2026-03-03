"""
Интеграционный тест: полный цикл арбитражного трейдера на доменном уровне.

Симулирует реальный поток:
1. Пары свечей с двух бирж (ArbitrageCandle)
2. Стратегия определяет спред и генерирует сигналы
3. Позиции открываются/закрываются на обеих биржах одновременно

Стратегия: SpreadReversionArbitrageStrategy
  open_threshold=1.0% — открываем когда |спред| > 1%
  close_threshold=0.2% — закрываем когда |спред| < 0.2%

Риск-менеджер: PSAllInArbitrageRiskManager
  Позиция = весь баланс
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from arbitrage_traders.domain.risk_managers import PSAllInArbitrageRiskManager
from arbitrage_traders.domain.schemas import (
    ArbitrageCandle,
    PositionCloseReason,
    PositionStatus,
    PositionType,
    SignalType,
    TraderStatus,
)
from arbitrage_traders.domain.strategies import SpreadReversionArbitrageStrategy
from arbitrage_traders.domain.traders.traders import ArbitrageTrader
from exchanges.domain import ExchangeCandle, Timeframe, TradingPair, TradingPairType

BASE_TIME = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)


def _candle(
    candle_id: int,
    dt_unix: int,
    o: float,
    h: float,
    low: float,
    c: float,
    v: float = 1_000_000,
) -> ExchangeCandle:
    """Создаёт доменную свечу."""
    return ExchangeCandle(
        id=candle_id,
        dt_unix=dt_unix,
        open=Decimal(str(o)),
        high=Decimal(str(h)),
        low=Decimal(str(low)),
        close=Decimal(str(c)),
        volume=Decimal(str(v)),
    )


def _arb_candle(
    hour: int,
    left_close: float,
    right_close: float,
    delta: float = 200,
) -> ArbitrageCandle:
    """Создаёт пару свечей для арбитража."""
    ts = BASE_TIME + timedelta(hours=hour)
    dt_unix = int(ts.timestamp() * 1000)
    left = _candle(
        candle_id=hour * 2 + 1,
        dt_unix=dt_unix,
        o=left_close - 100,
        h=left_close + delta,
        low=left_close - delta,
        c=left_close,
    )
    right = _candle(
        candle_id=hour * 2 + 2,
        dt_unix=dt_unix,
        o=right_close - 100,
        h=right_close + delta,
        low=right_close - delta,
        c=right_close,
    )
    return ArbitrageCandle(left=left, right=right)


def _mock_exchange_client():
    """Мок exchange client с async context manager."""
    mock = MagicMock()
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=False)
    return mock


def _make_arb_trader(**overrides) -> ArbitrageTrader:
    """Создаёт арбитражного трейдера с реальной стратегией."""
    defaults = {
        "trading_pair": TradingPair(
            name="BTC/USDT",
            symbol="BTC/USDT:USDT",
            type=TradingPairType.FUTURES,
            min_amount=Decimal("0.001"),
            max_amount=Decimal("1000"),
            fee_percent=Decimal("0.1"),
        ),
        "timeframe": Timeframe.ONE_HOUR,
        "left_exchange_client": _mock_exchange_client(),
        "right_exchange_client": _mock_exchange_client(),
        "strategy": SpreadReversionArbitrageStrategy(
            open_threshold=1.0,
            close_threshold=0.2,
        ),
        "risk_manager": PSAllInArbitrageRiskManager(),
        "initial_balance": Decimal("10000.00"),
        "balance": Decimal("10000.00"),
        "use_fixed_balance": True,
        "max_positions_count": 1,
        "create_new_orders": False,
        "close_position_by_strategy": True,
        "close_position_by_opposite_signal": True,
        "status": TraderStatus.ENABLED,
    }
    defaults.update(overrides)
    return ArbitrageTrader(**defaults)


def _print_arb_state(label: str, trader: ArbitrageTrader) -> None:
    """Выводит состояние арбитражного трейдера."""
    signals = list(trader.signals)
    opened = list(trader.opened_positions)
    closed = list(trader.closed_positions)

    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")
    print(f"  Сигналов: {len(signals)}")
    if signals:
        last = signals[-1]
        print(
            f"  Последний: left={last.left_type} right={last.right_type}"
            f" | data={last.data}"
        )
    print(f"  Позиций: открытых={len(opened)}, закрытых={len(closed)}")
    for p in trader.positions:
        icon = "OPEN" if p.status == PositionStatus.OPENED else "CLOSED"
        print(
            f"  [{icon}] {p.type} | left={p.left_type} right={p.right_type}"
            f" | amount={p.amount}"
        )
        print(f"    left: open={p.left_open_price} close={p.left_close_price}")
        print(f"    right: open={p.right_open_price} close={p.right_close_price}")
        if p.is_closed:
            print(f"    reason={p.close_reason} | PnL={p.pnl}")


class TestArbitrageTraderDomainIntegration:
    """
    Полный цикл арбитражного трейдера:
    свечи → спред → сигнал → позиция → закрытие.
    """

    @pytest.mark.asyncio
    async def test_full_arbitrage_cycle(self):
        """
        Полный цикл:
        1. Нет спреда → WAIT
        2. Спред расходится (left дешевле) → BUY left / SELL right → LONG
        3. Спред сходится обратно → стратегия закрывает → PnL > 0
        4. Спред в другую сторону → SELL left / BUY right → SHORT
        5. Спред сходится → закрытие SHORT
        """
        trader = _make_arb_trader()

        # ── Фаза 1: Нет спреда (одинаковые цены) → WAIT ──
        for i in range(3):
            candle = _arb_candle(hour=i, left_close=50000, right_close=50000)
            await trader.handle_candle(candle)

        _print_arb_state("Фаза 1: Нет спреда", trader)
        assert len(trader.positions) == 0, "Не должно быть позиций при нулевом спреде"

        # ── Фаза 2: Спред расходится — left дешевле ──
        # spread = (left - right) / right * 100
        # left=49000, right=50000 → spread = -2% < -1% → BUY left, SELL right
        candle = _arb_candle(hour=3, left_close=49000, right_close=50000)
        await trader.handle_candle(candle)

        _print_arb_state("Фаза 2: Спред -2% (left дешевле)", trader)

        opened = list(trader.opened_positions)
        assert len(opened) == 1, "Должна быть открыта 1 позиция"
        pos = opened[0]
        assert pos.left_type == PositionType.LONG
        assert pos.right_type == PositionType.SHORT
        assert pos.type == PositionType.LONG  # main type = left

        # ── Фаза 3: Спред сходится обратно → закрытие ──
        # spread = (50100 - 50000) / 50000 * 100 = 0.2%
        # |spread| = 0.2% ≤ 0.2% → close_threshold → закрываем LONG
        candle = _arb_candle(hour=4, left_close=50100, right_close=50000)
        await trader.handle_candle(candle)

        _print_arb_state("Фаза 3: Спред сошёлся", trader)

        closed = list(trader.closed_positions)
        assert len(closed) == 1, "Позиция должна быть закрыта"
        assert closed[0].close_reason == PositionCloseReason.STRATEGY
        assert closed[0].pnl is not None
        print(f"  PnL первой позиции: {closed[0].pnl}")

        # ── Фаза 4: Спред в другую сторону — left дороже ──
        # left=51000, right=50000 → spread = +2% > 1% → SELL left, BUY right
        candle = _arb_candle(hour=5, left_close=51000, right_close=50000)
        await trader.handle_candle(candle)

        _print_arb_state("Фаза 4: Спред +2% (left дороже)", trader)

        opened = list(trader.opened_positions)
        assert len(opened) == 1, "Должна быть открыта SHORT позиция"
        pos = opened[0]
        assert pos.left_type == PositionType.SHORT
        assert pos.right_type == PositionType.LONG

        # ── Фаза 5: Спред сходится → закрытие SHORT ──
        candle = _arb_candle(hour=6, left_close=50050, right_close=50000)
        await trader.handle_candle(candle)

        _print_arb_state("Фаза 5: Спред сошёлся (SHORT)", trader)

        closed = list(trader.closed_positions)
        assert len(closed) == 2, "Обе позиции должны быть закрыты"

        total_pnl = trader.get_pnl()
        print(f"\n  Итоговый PnL: {total_pnl}")
        print(f"  ROI: {trader.get_roi():.2f}%")

    @pytest.mark.asyncio
    async def test_no_spread_no_positions(self):
        """Одинаковые цены → спред=0 → нет позиций."""
        trader = _make_arb_trader()

        for i in range(10):
            candle = _arb_candle(hour=i, left_close=50000, right_close=50000)
            await trader.handle_candle(candle)

        assert len(trader.positions) == 0
        for s in trader.signals:
            assert s.left_type == SignalType.WAIT
            assert s.right_type == SignalType.WAIT

    @pytest.mark.asyncio
    async def test_spread_below_threshold_no_position(self):
        """Спред 0.5% < open_threshold=1.0% → нет позиции."""
        trader = _make_arb_trader()

        # spread = (49750 - 50000) / 50000 * 100 = -0.5%
        candle = _arb_candle(hour=0, left_close=49750, right_close=50000)
        await trader.handle_candle(candle)

        assert len(trader.positions) == 0

    @pytest.mark.asyncio
    async def test_negative_spread_opens_long(self):
        """Отрицательный спред > threshold → LONG (BUY left, SELL right)."""
        trader = _make_arb_trader()

        # spread = (48500 - 50000) / 50000 * 100 = -3%
        candle = _arb_candle(hour=0, left_close=48500, right_close=50000)
        await trader.handle_candle(candle)

        opened = list(trader.opened_positions)
        assert len(opened) == 1
        pos = opened[0]
        assert pos.type == PositionType.LONG
        assert pos.left_type == PositionType.LONG
        assert pos.right_type == PositionType.SHORT

    @pytest.mark.asyncio
    async def test_positive_spread_opens_short(self):
        """Положительный спред > threshold → SHORT (SELL left, BUY right)."""
        trader = _make_arb_trader()

        # spread = (51500 - 50000) / 50000 * 100 = +3%
        candle = _arb_candle(hour=0, left_close=51500, right_close=50000)
        await trader.handle_candle(candle)

        opened = list(trader.opened_positions)
        assert len(opened) == 1
        pos = opened[0]
        assert pos.type == PositionType.SHORT
        assert pos.left_type == PositionType.SHORT
        assert pos.right_type == PositionType.LONG

    @pytest.mark.asyncio
    async def test_opposite_signal_closes_position(self):
        """Противоположный сигнал закрывает позицию."""
        trader = _make_arb_trader()
        trader.close_position_by_strategy = False  # только opposite_signal

        # Открываем LONG (left дешевле)
        candle = _arb_candle(hour=0, left_close=49000, right_close=50000)
        await trader.handle_candle(candle)
        assert len(list(trader.opened_positions)) == 1

        # Сигнал в противоположную сторону (left дороже)
        candle = _arb_candle(hour=1, left_close=51500, right_close=50000)
        await trader.handle_candle(candle)

        _print_arb_state("Opposite signal", trader)

        closed = list(trader.closed_positions)
        assert len(closed) == 1
        assert closed[0].close_reason == PositionCloseReason.OPPOSITE_SIGNAL

    @pytest.mark.asyncio
    async def test_max_positions_limit(self):
        """Не открываем больше max_positions_count."""
        trader = _make_arb_trader(max_positions_count=1)

        # Открываем одну позицию
        candle = _arb_candle(hour=0, left_close=49000, right_close=50000)
        await trader.handle_candle(candle)
        assert len(list(trader.opened_positions)) == 1

        # Ещё сигнал в ту же сторону — позиция не открывается
        candle = _arb_candle(hour=1, left_close=48500, right_close=50000)
        await trader.handle_candle(candle)
        assert len(trader.positions) == 1

    @pytest.mark.asyncio
    async def test_paused_trader_no_trades(self):
        """PAUSED трейдер генерирует сигналы, но не торгует."""
        trader = _make_arb_trader(status=TraderStatus.PAUSED)

        candle = _arb_candle(hour=0, left_close=49000, right_close=50000)
        await trader.handle_candle(candle)

        assert len(trader.signals) == 1
        assert trader.signals[0].left_type == SignalType.BUY
        assert len(trader.positions) == 0

    @pytest.mark.asyncio
    async def test_multiple_round_trips(self):
        """Несколько циклов открытие → закрытие."""
        trader = _make_arb_trader()

        # Цикл 1: LONG
        candle = _arb_candle(hour=0, left_close=49000, right_close=50000)
        await trader.handle_candle(candle)
        candle = _arb_candle(hour=1, left_close=50000, right_close=50000)
        await trader.handle_candle(candle)

        # Цикл 2: SHORT
        candle = _arb_candle(hour=2, left_close=51500, right_close=50000)
        await trader.handle_candle(candle)
        candle = _arb_candle(hour=3, left_close=50000, right_close=50000)
        await trader.handle_candle(candle)

        # Цикл 3: LONG снова
        candle = _arb_candle(hour=4, left_close=48000, right_close=50000)
        await trader.handle_candle(candle)
        candle = _arb_candle(hour=5, left_close=50050, right_close=50000)
        await trader.handle_candle(candle)

        _print_arb_state("3 round trips", trader)

        closed = list(trader.closed_positions)
        assert len(closed) == 3, (
            f"Должно быть 3 закрытых позиции, найдено {len(closed)}"
        )

        # Все закрыты по стратегии
        for p in closed:
            assert p.close_reason == PositionCloseReason.STRATEGY

        total_pnl = trader.get_pnl()
        print(f"\n  Итоговый PnL за 3 цикла: {total_pnl}")

    @pytest.mark.asyncio
    async def test_pnl_positive_on_spread_convergence(self):
        """Арбитраж на сходящемся спреде даёт положительный PnL."""
        trader = _make_arb_trader()

        # Открываем LONG: left=48000 (дешевле), right=50000
        candle = _arb_candle(hour=0, left_close=48000, right_close=50000)
        await trader.handle_candle(candle)

        # Закрываем: left=50000, right=50000 (спред = 0)
        candle = _arb_candle(hour=1, left_close=50000, right_close=50000)
        await trader.handle_candle(candle)

        closed = list(trader.closed_positions)
        assert len(closed) == 1
        pos = closed[0]

        # LONG на left: buy 48000, sell 50000 → profit
        # SHORT на right: sell 50000, buy 50000 → breakeven
        assert pos.pnl is not None
        assert pos.pnl > 0, f"PnL должен быть положительным: {pos.pnl}"

    @pytest.mark.asyncio
    async def test_spread_widens_further_no_close(self):
        """Если спред расходится ещё больше, позиция не закрывается."""
        trader = _make_arb_trader()

        # Открываем LONG: spread = -2%
        candle = _arb_candle(hour=0, left_close=49000, right_close=50000)
        await trader.handle_candle(candle)
        assert len(list(trader.opened_positions)) == 1

        # Спред расходится ещё больше: spread = -4%
        candle = _arb_candle(hour=1, left_close=48000, right_close=50000)
        await trader.handle_candle(candle)

        # Позиция всё ещё открыта
        assert len(list(trader.opened_positions)) == 1
        assert len(list(trader.closed_positions)) == 0
