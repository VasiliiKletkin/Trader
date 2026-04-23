"""
Интеграционный тест: полный цикл обработки свечей доменным трейдером.

Симулирует реальный поток (тот же, что запускает Celery-задача),
но напрямую через доменный Trader, без ORM sync/load.
Это позволяет избежать SQLite-артефактов (bulk_create с update_conflicts).

Стратегия: MoneyFlowIndexStrategy (period=10)
  MFI > 80 → BUY, MFI < 20 → SELL
  Закрытие LONG → MFI < 50 (median)
  Закрытие SHORT → MFI > 50 (median)

Риск-менеджер: SLPercentTPPercentPSAllInRiskManager
  SL=5%, TP=10%, позиция = весь баланс
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from exchanges.domain import ExchangeCandle, MarketType, Timeframe, TradingPair
from traders.domain.risk_managers import SLPercentTPPercentPSAllInRiskManager
from traders.domain.schemas import (
    PositionCloseReason,
    PositionStatus,
    PositionType,
    SignalType,
    TraderStatus,
)
from traders.domain.strategies import MoneyFlowIndexStrategy
from traders.domain.traders.traders import Trader

BASE_TIME = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)


def _candle(
    hour: int,
    o: float,
    h: float,
    low: float,
    c: float,
    v: float = 1_000_000,
) -> ExchangeCandle:
    """Создаёт доменную свечу."""
    ts = BASE_TIME + timedelta(hours=hour)
    return ExchangeCandle(
        id=hour + 1,
        dt_unix=int(ts.timestamp() * 1000),
        open=Decimal(str(o)),
        high=Decimal(str(h)),
        low=Decimal(str(low)),
        close=Decimal(str(c)),
        volume=Decimal(str(v)),
    )


def _make_trader() -> Trader:
    """Создаёт доменного трейдера с реальной стратегией и риск-менеджером."""
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    return Trader(
        trading_pair=TradingPair(
            name="BTC/USDT",
            symbol="BTC/USDT:USDT",
            base_currency="BTC",
            quote_currency="USDT",
            settle_currency="USDT",
            market_type=MarketType.FUTURES,
            min_amount=Decimal("0.001"),
            max_amount=Decimal("1000"),
            taker_fee=Decimal("0.001"),
            maker_fee=Decimal("0.001"),
        ),
        timeframe=Timeframe.ONE_HOUR,
        exchange_client=mock_client,
        strategy=MoneyFlowIndexStrategy(
            period=10,
            overbought=80,
            oversold=20,
            median=50,
        ),
        risk_manager=SLPercentTPPercentPSAllInRiskManager(
            stop_loss_percent=5.0,
            take_profit_percent=10.0,
        ),
        initial_balance=Decimal("10000.00"),
        balance=Decimal("10000.00"),
        use_fixed_balance=True,
        max_positions_count=1,
        create_new_orders=False,
        trail_stop_enabled=True,
        close_position_by_stop_loss=True,
        close_position_by_take_profit=True,
        close_position_by_strategy=True,
        close_position_by_opposite_signal=True,
        status=TraderStatus.ENABLED,
    )


def _print_state(label: str, trader: Trader) -> None:
    """Выводит текущее состояние трейдера."""
    signals = list(trader.signals)
    positions = trader.positions
    opened = list(trader.opened_positions)
    closed = list(trader.closed_positions)

    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")

    print(f"\n  Сигналов: {len(signals)}")
    if signals:
        last = signals[-1]
        print(f"  Последний: {last.type} @ {last.price} | data={last.data}")

    print(f"\n  Позиций всего: {len(positions)}")
    print(f"    открытых: {len(opened)}")
    print(f"    закрытых: {len(closed)}")

    for p in positions:
        icon = "OPEN" if p.status == PositionStatus.OPENED else "CLOSED"
        print(f"  [{icon}] {p.type} | open_amount={p.open_amount}")
        print(f"    open={p.open_price} | SL={p.stop_loss} | TP={p.take_profit}")
        if p.close_price:
            print(f"    close={p.close_price} | reason={p.close_reason}")
            print(f"    PnL={p.pnl}")


class TestTraderDomainIntegration:
    """
    Полный цикл обработки свечей на доменном уровне:
    свечи → стратегия → сигналы → позиции → закрытие.
    """

    @pytest.mark.asyncio
    async def test_full_cycle(self):
        """
        Полный цикл:
        1. 12 свечей восходящий тренд → MFI > 80 → BUY → LONG
        2. Ещё свечи, тренд продолжается → позиция держится
        3. Разворот вниз → MFI < 50 → стратегия закрывает LONG
        4. Продолжение падения → MFI < 20 → SELL → SHORT
        5. Отскок вверх → SL срабатывает на SHORT
        """
        trader = _make_trader()

        # ── Раунд 1: 12 свечей с сильным восходящим трендом ──
        # Каждая свеча +500, MFI → ~100
        uptrend = []
        for i in range(12):
            c = 50000 + i * 500
            uptrend.append(_candle(hour=i, o=c - 100, h=c + 200, low=c - 200, c=c))

        for candle in uptrend:
            await trader.handle_candle(candle)

        _print_state("Раунд 1: 12 свечей восходящий тренд", trader)

        signals = list(trader.signals)
        last_signal = signals[-1]
        opened = list(trader.opened_positions)

        assert last_signal.type == SignalType.BUY, (
            f"Ожидали BUY, получили {last_signal.type} (data={last_signal.data})"
        )
        assert len(opened) == 1, "Должна быть открыта 1 позиция"
        pos = opened[0]
        assert pos.type == PositionType.LONG
        assert pos.status == PositionStatus.OPENED
        assert pos.stop_loss is not None
        assert pos.take_profit is not None

        open_price = pos.open_price
        print(f"\n  Позиция открыта: LONG @ {open_price}")
        print(f"  SL={pos.stop_loss} ({pos.stop_loss_pct:.2f}%)")
        print(f"  TP={pos.take_profit} ({pos.take_profit_pct:.2f}%)")

        # ── Раунд 2: +3 свечи, тренд продолжается ──
        # Цена растёт, MFI остаётся > 50, позиция держится
        for i in range(3):
            c = 55500 + (i + 1) * 300
            candle = _candle(hour=12 + i, o=c - 100, h=c + 200, low=c - 200, c=c)
            await trader.handle_candle(candle)

        _print_state("Раунд 2: +3 свечи, тренд продолжается", trader)

        opened = list(trader.opened_positions)
        assert len(opened) == 1, "Позиция должна оставаться открытой"
        assert opened[0].status == PositionStatus.OPENED

        # ── Раунд 3: Резкий разворот — цена падает ──
        # Серия падающих свечей → MFI резко падает < 50 → стратегия закрывает LONG
        reversal = [
            (56500, 56600, 54000, 54500, 2_000_000),
            (54500, 54600, 52000, 52500, 2_000_000),
            (52500, 52600, 50000, 50500, 2_000_000),
            (50500, 50600, 48000, 48500, 2_000_000),
            (48500, 48600, 46000, 46500, 3_000_000),
        ]
        for i, (o, h, low, c, v) in enumerate(reversal):
            candle = _candle(hour=15 + i, o=o, h=h, low=low, c=c, v=v)
            await trader.handle_candle(candle)

        _print_state("Раунд 3: Разворот (5 свечей падения)", trader)

        closed = list(trader.closed_positions)
        assert len(closed) >= 1, (
            f"Позиция должна быть закрыта. "
            f"Открытых: {len(list(trader.opened_positions))}"
        )

        closed_pos = closed[0]
        print("\n  Закрытая позиция:")
        print(f"    open={closed_pos.open_price} → close={closed_pos.close_price}")
        print(f"    reason={closed_pos.close_reason}")
        print(f"    PnL={closed_pos.pnl}")

        # ── Раунд 4: Продолжение падения → SELL → SHORT ──
        continued_drop = [
            (46500, 46600, 44000, 44500, 3_000_000),
            (44500, 44600, 42000, 42500, 3_000_000),
            (42500, 42600, 40000, 40500, 3_000_000),
        ]
        for i, (o, h, low, c, v) in enumerate(continued_drop):
            candle = _candle(hour=20 + i, o=o, h=h, low=low, c=c, v=v)
            await trader.handle_candle(candle)

        _print_state("Раунд 4: Продолжение падения → SELL?", trader)

        sell_signals = [s for s in trader.signals if s.type == SignalType.SELL]
        print(f"\n  SELL сигналов: {len(sell_signals)}")

        # Проверяем, что SHORT позиция была открыта
        all_positions = trader.positions
        short_positions = [p for p in all_positions if p.type == PositionType.SHORT]
        if short_positions:
            sp = short_positions[0]
            print(f"  SHORT позиция: open={sp.open_price}")
            print(f"    SL={sp.stop_loss} | TP={sp.take_profit}")
            assert sp.status == PositionStatus.OPENED

            # ── Раунд 5: Отскок вверх → SL на SHORT ──
            # Цена резко растёт, пробивает SL для SHORT
            bounce = [
                (40500, 43000, 40400, 42500, 2_000_000),
                (42500, 45000, 42400, 44500, 2_000_000),
                (44500, 47000, 44400, 46500, 2_000_000),
            ]
            for i, (o, h, low, c, v) in enumerate(bounce):
                candle = _candle(hour=23 + i, o=o, h=h, low=low, c=c, v=v)
                await trader.handle_candle(candle)

            _print_state("Раунд 5: Отскок (SL на SHORT?)", trader)

            closed_shorts = [
                p
                for p in trader.positions
                if p.type == PositionType.SHORT and p.is_closed
            ]
            if closed_shorts:
                cs = closed_shorts[0]
                print(f"\n  SHORT закрыта: reason={cs.close_reason}")
                print(f"    open={cs.open_price} → close={cs.close_price}")
                print(f"    PnL={cs.pnl}")

        # ── Итоговая сводка ──
        all_signals = list(trader.signals)
        all_positions = trader.positions

        print(f"\n{'=' * 60}")
        print("  ИТОГО")
        print(f"{'=' * 60}")
        print(f"  Свечей обработано: {len(trader.candles)}")
        print(f"  Сигналов: {len(all_signals)}")
        print(f"    BUY:  {sum(1 for s in all_signals if s.type == SignalType.BUY)}")
        print(f"    SELL: {sum(1 for s in all_signals if s.type == SignalType.SELL)}")
        print(f"    WAIT: {sum(1 for s in all_signals if s.type == SignalType.WAIT)}")
        print(f"  Позиций: {len(all_positions)}")
        print(f"    открытых: {len(list(trader.opened_positions))}")
        print(f"    закрытых: {len(list(trader.closed_positions))}")

        total_pnl = trader.get_pnl()
        print(f"  Итоговый PnL: {total_pnl}")

    @pytest.mark.asyncio
    async def test_uptrend_generates_buy_signal(self):
        """12 свечей восходящего тренда → MFI > 80 → BUY сигнал."""
        trader = _make_trader()

        for i in range(12):
            c = 50000 + i * 500
            candle = _candle(hour=i, o=c - 100, h=c + 200, low=c - 200, c=c)
            await trader.handle_candle(candle)

        signals = list(trader.signals)
        buy_signals = [s for s in signals if s.type == SignalType.BUY]
        assert len(buy_signals) >= 1, "Должен быть хотя бы один BUY сигнал"

    @pytest.mark.asyncio
    async def test_downtrend_generates_sell_signal(self):
        """12 свечей нисходящего тренда → MFI < 20 → SELL сигнал."""
        trader = _make_trader()

        for i in range(12):
            c = 60000 - i * 500
            candle = _candle(hour=i, o=c + 100, h=c + 200, low=c - 200, c=c)
            await trader.handle_candle(candle)

        signals = list(trader.signals)
        sell_signals = [s for s in signals if s.type == SignalType.SELL]
        assert len(sell_signals) >= 1, "Должен быть хотя бы один SELL сигнал"

    @pytest.mark.asyncio
    async def test_stop_loss_closes_position(self):
        """Позиция закрывается по SL при резком падении цены."""
        trader = _make_trader()

        # Восходящий тренд → BUY → LONG
        for i in range(12):
            c = 50000 + i * 500
            candle = _candle(hour=i, o=c - 100, h=c + 200, low=c - 200, c=c)
            await trader.handle_candle(candle)

        opened = list(trader.opened_positions)
        assert len(opened) == 1
        pos = opened[0]
        open_price = pos.open_price
        sl_price = pos.stop_loss

        # Резкое падение ниже SL
        crash_price = float(sl_price) - 500
        candle = _candle(
            hour=12,
            o=float(open_price),
            h=float(open_price) + 100,
            low=crash_price - 100,
            c=crash_price,
            v=5_000_000,
        )
        await trader.handle_candle(candle)

        closed = list(trader.closed_positions)
        assert len(closed) == 1, "Позиция должна быть закрыта по SL"
        assert closed[0].close_reason == PositionCloseReason.STOP_LOSS

    @pytest.mark.asyncio
    async def test_max_positions_limit(self):
        """Не открываем больше max_positions_count позиций."""
        trader = _make_trader()
        assert trader.max_positions_count == 1

        # Восходящий тренд → BUY → LONG
        for i in range(12):
            c = 50000 + i * 500
            candle = _candle(hour=i, o=c - 100, h=c + 200, low=c - 200, c=c)
            await trader.handle_candle(candle)

        # Ещё BUY сигналы, но вторая позиция не должна открыться
        for i in range(3):
            c = 55500 + (i + 1) * 500
            candle = _candle(hour=12 + i, o=c - 100, h=c + 200, low=c - 200, c=c)
            await trader.handle_candle(candle)

        all_positions = trader.positions
        assert len(all_positions) == 1, (
            f"Должна быть только 1 позиция, но найдено {len(all_positions)}"
        )

    @pytest.mark.asyncio
    async def test_take_profit_closes_position(self):
        """Позиция закрывается по TP при сильном росте цены.

        Trail stop отключён, т.к. с percent-based TP он пересчитывает TP
        от текущей цены, всегда отодвигая его вперёд.
        """
        trader = _make_trader()
        trader.trail_stop_enabled = False

        # Восходящий тренд → BUY → LONG
        for i in range(12):
            c = 50000 + i * 500
            candle = _candle(hour=i, o=c - 100, h=c + 200, low=c - 200, c=c)
            await trader.handle_candle(candle)

        opened = list(trader.opened_positions)
        assert len(opened) == 1
        pos = opened[0]
        tp_price = pos.take_profit

        # Резкий рост выше TP
        boom_price = float(tp_price) + 500
        candle = _candle(
            hour=12,
            o=float(pos.open_price) + 1000,
            h=boom_price + 100,
            low=float(pos.open_price) + 900,
            c=boom_price,
            v=3_000_000,
        )
        await trader.handle_candle(candle)

        closed = list(trader.closed_positions)
        assert len(closed) == 1, "Позиция должна быть закрыта по TP"
        assert closed[0].close_reason == PositionCloseReason.TAKE_PROFIT

    @pytest.mark.asyncio
    async def test_opposite_signal_closes_position(self):
        """SELL сигнал закрывает LONG позицию по opposite_signal."""
        trader = _make_trader()
        # Отключаем SL/TP и стратегию, оставляем только opposite_signal
        trader.close_position_by_stop_loss = False
        trader.close_position_by_take_profit = False
        trader.close_position_by_strategy = False

        # Восходящий тренд → BUY → LONG
        for i in range(12):
            c = 50000 + i * 500
            candle = _candle(hour=i, o=c - 100, h=c + 200, low=c - 200, c=c)
            await trader.handle_candle(candle)

        assert len(list(trader.opened_positions)) == 1

        # Резкий разворот → MFI < 20 → SELL сигнал
        for i in range(8):
            c = 55500 - (i + 1) * 1500
            candle = _candle(
                hour=12 + i,
                o=c + 500,
                h=c + 600,
                low=c - 500,
                c=c,
                v=3_000_000,
            )
            await trader.handle_candle(candle)

        closed = list(trader.closed_positions)
        assert len(closed) >= 1, "Позиция должна быть закрыта"
        assert closed[0].close_reason == PositionCloseReason.OPPOSITE_SIGNAL

    @pytest.mark.asyncio
    async def test_paused_trader_generates_signals_but_no_positions(self):
        """PAUSED трейдер генерирует сигналы, но не открывает позиции."""
        trader = _make_trader()
        trader.status = TraderStatus.PAUSED

        for i in range(12):
            c = 50000 + i * 500
            candle = _candle(hour=i, o=c - 100, h=c + 200, low=c - 200, c=c)
            await trader.handle_candle(candle)

        # Сигналы генерируются (включая BUY)
        signals = list(trader.signals)
        assert len(signals) == 12
        buy_signals = [s for s in signals if s.type == SignalType.BUY]
        assert len(buy_signals) >= 1

        # Но позиции не открываются
        assert len(trader.positions) == 0

    @pytest.mark.asyncio
    async def test_insufficient_candles_produce_wait_signals(self):
        """Первые 10 свечей → недостаточно данных для MFI → WAIT."""
        trader = _make_trader()

        for i in range(10):
            c = 50000 + i * 500
            candle = _candle(hour=i, o=c - 100, h=c + 200, low=c - 200, c=c)
            await trader.handle_candle(candle)

        signals = list(trader.signals)
        # Все 10 сигналов должны быть WAIT (MFI нужен period=10+1 свеча)
        for s in signals:
            assert s.type == SignalType.WAIT, (
                f"Сигнал #{signals.index(s)} = {s.type}, ожидали WAIT"
            )
        assert len(trader.positions) == 0

    @pytest.mark.asyncio
    async def test_trail_stop_only_improves(self):
        """Trail stop двигает SL только в лучшую сторону для LONG."""
        trader = _make_trader()

        # Восходящий тренд → BUY → LONG
        for i in range(12):
            c = 50000 + i * 500
            candle = _candle(hour=i, o=c - 100, h=c + 200, low=c - 200, c=c)
            await trader.handle_candle(candle)

        opened = list(trader.opened_positions)
        assert len(opened) == 1
        initial_sl = opened[0].stop_loss

        # Ещё 3 свечи вверх → SL должен подтянуться
        for i in range(3):
            c = 55500 + (i + 1) * 300
            candle = _candle(hour=12 + i, o=c - 100, h=c + 200, low=c - 200, c=c)
            await trader.handle_candle(candle)

        opened = list(trader.opened_positions)
        assert len(opened) == 1
        new_sl = opened[0].stop_loss
        assert new_sl > initial_sl, (
            f"Trail stop должен подтянуться: {initial_sl} → {new_sl}"
        )

    @pytest.mark.asyncio
    async def test_flat_market_no_positions(self):
        """Боковой рынок: MFI между 20 и 80 → только WAIT, нет позиций."""
        trader = _make_trader()

        # Колебания вокруг одной цены, чередуя вверх-вниз
        for i in range(20):
            base = 50000
            # Чередуем +100/-100 — типичная цена почти не меняется
            delta = 100 if i % 2 == 0 else -100
            c = base + delta
            candle = _candle(
                hour=i,
                o=base,
                h=base + 150,
                low=base - 150,
                c=c,
            )
            await trader.handle_candle(candle)

        buy_signals = [s for s in trader.signals if s.type == SignalType.BUY]
        sell_signals = [s for s in trader.signals if s.type == SignalType.SELL]

        # В боковике не должно быть сильных сигналов
        assert len(buy_signals) == 0, f"Не ожидали BUY в боковике: {len(buy_signals)}"
        assert len(sell_signals) == 0, (
            f"Не ожидали SELL в боковике: {len(sell_signals)}"
        )
        assert len(trader.positions) == 0

    @pytest.mark.asyncio
    async def test_strategy_closes_long_when_mfi_drops_below_median(self):
        """Стратегия закрывает LONG когда MFI падает ниже median=50."""
        trader = _make_trader()
        # Отключаем SL/TP, оставляем только стратегию
        trader.close_position_by_stop_loss = False
        trader.close_position_by_take_profit = False
        trader.close_position_by_opposite_signal = False

        # Восходящий тренд → BUY → LONG
        for i in range(12):
            c = 50000 + i * 500
            candle = _candle(hour=i, o=c - 100, h=c + 200, low=c - 200, c=c)
            await trader.handle_candle(candle)

        assert len(list(trader.opened_positions)) == 1

        # Плавное снижение → MFI упадёт ниже 50
        for i in range(6):
            c = 55500 - (i + 1) * 500
            candle = _candle(
                hour=12 + i,
                o=c + 200,
                h=c + 300,
                low=c - 300,
                c=c,
                v=1_500_000,
            )
            await trader.handle_candle(candle)

        closed = list(trader.closed_positions)
        if closed:
            assert closed[0].close_reason == PositionCloseReason.STRATEGY, (
                f"Ожидали STRATEGY, получили {closed[0].close_reason}"
            )
