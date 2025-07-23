"""
Тесты для Django модели трейдера.
"""

from datetime import datetime, timezone
from decimal import Decimal

from django.test import TestCase
from exchanges.models import Exchange, ExchangeClient, TradingPair
from risk_managers.models import RiskManager
from strategies.models import Strategy
from core.utils.types import (
    PositionStatus,
    PositionType,
    Timeframe,
    TraderStatus,
)

from .models import Trader, TraderPosition


class TestTraderModel(TestCase):
    """Тесты для модели Trader."""

    def setUp(self):
        """Настройка тестового окружения."""
        # Создаем необходимые зависимости
        self.exchange = Exchange.objects.create(
            name="Test Exchange",
            is_active=True,
        )

        self.exchange_client = ExchangeClient.objects.create(
            exchange=self.exchange,
            name="Test Client",
            is_active=True,
        )

        self.trading_pair = TradingPair.objects.create(
            exchange=self.exchange,
            name="BTC/USDT",
            symbol="BTCUSDT",
            is_active=True,
        )

        self.strategy = Strategy.objects.create(
            name="Test Strategy",
            strategy_class="MFIStrategy",
            is_active=True,
        )

        self.risk_manager = RiskManager.objects.create(
            name="Test Risk Manager",
            risk_manager_class="FixedRiskManager",
            is_active=True,
        )

    def test_trader_creation(self):
        """Тест создания трейдера."""
        trader = Trader.objects.create(
            exchange_client=self.exchange_client,
            trading_pair=self.trading_pair,
            timeframe=Timeframe.ONE_MINUTE,
            strategy=self.strategy,
            risk_manager=self.risk_manager,
            initial_balance=Decimal("1000.00"),
            max_drawdown_pct=Decimal("10.00"),
            max_positions_count=3,
        )

        self.assertEqual(trader.exchange_client, self.exchange_client)
        self.assertEqual(trader.trading_pair, self.trading_pair)
        self.assertEqual(trader.timeframe, Timeframe.ONE_MINUTE)
        self.assertEqual(trader.strategy, self.strategy)
        self.assertEqual(trader.risk_manager, self.risk_manager)
        self.assertEqual(trader.initial_balance, Decimal("1000.00"))
        self.assertEqual(trader.max_drawdown_pct, Decimal("10.00"))
        self.assertEqual(trader.max_positions_count, 3)
        self.assertEqual(trader.status, TraderStatus.DISABLED)
        self.assertFalse(trader.favorite)
        self.assertFalse(trader.trail_stop_enabled)

    def test_trader_string_representation(self):
        """Тест строкового представления трейдера."""
        trader = Trader.objects.create(
            exchange_client=self.exchange_client,
            trading_pair=self.trading_pair,
            timeframe=Timeframe.ONE_MINUTE,
            strategy=self.strategy,
            risk_manager=self.risk_manager,
        )

        expected_str = (
            f"Отключен | {trader.pk} | {self.exchange_client} | " f"{self.strategy}"
        )
        self.assertEqual(str(trader), expected_str)

    def test_trader_enable_disable(self):
        """Тест включения и отключения трейдера."""
        trader = Trader.objects.create(
            exchange_client=self.exchange_client,
            trading_pair=self.trading_pair,
            timeframe=Timeframe.ONE_MINUTE,
            strategy=self.strategy,
            risk_manager=self.risk_manager,
        )

        # Проверяем начальное состояние
        self.assertEqual(trader.status, TraderStatus.DISABLED)

        # Включаем трейдера
        trader.enable()
        trader.refresh_from_db()
        self.assertEqual(trader.status, TraderStatus.ENABLED)

        # Отключаем трейдера
        trader.disable()
        trader.refresh_from_db()
        self.assertEqual(trader.status, TraderStatus.DISABLED)

    def test_current_balance_calculation(self):
        """Тест расчета текущего баланса."""
        trader = Trader.objects.create(
            exchange_client=self.exchange_client,
            trading_pair=self.trading_pair,
            timeframe=Timeframe.ONE_MINUTE,
            strategy=self.strategy,
            risk_manager=self.risk_manager,
            initial_balance=Decimal("1000.00"),
        )

        # Без ордеров баланс должен равняться начальному
        self.assertEqual(trader.current_balance, Decimal("1000.00"))

    def test_winrate_calculation_no_positions(self):
        """Тест расчета винрейта без позиций."""
        trader = Trader.objects.create(
            exchange_client=self.exchange_client,
            trading_pair=self.trading_pair,
            timeframe=Timeframe.ONE_MINUTE,
            strategy=self.strategy,
            risk_manager=self.risk_manager,
        )

        winrate = trader.get_winrate()
        self.assertEqual(winrate, 0.0)

    def test_winrate_calculation_with_positions(self):
        """Тест расчета винрейта с позициями."""
        trader = Trader.objects.create(
            exchange_client=self.exchange_client,
            trading_pair=self.trading_pair,
            timeframe=Timeframe.ONE_MINUTE,
            strategy=self.strategy,
            risk_manager=self.risk_manager,
        )

        # Создаем прибыльную LONG позицию
        TraderPosition.objects.create(
            trader=trader,
            type=PositionType.LONG,
            status=PositionStatus.CLOSED,
            amount=Decimal("0.1"),
            open_price=Decimal("50000"),
            close_price=Decimal("55000"),  # прибыль
            opened_at=datetime.now(timezone.utc),
            closed_at=datetime.now(timezone.utc),
        )

        # Создаем убыточную LONG позицию
        TraderPosition.objects.create(
            trader=trader,
            type=PositionType.LONG,
            status=PositionStatus.CLOSED,
            amount=Decimal("0.1"),
            open_price=Decimal("50000"),
            close_price=Decimal("45000"),  # убыток
            opened_at=datetime.now(timezone.utc),
            closed_at=datetime.now(timezone.utc),
        )

        winrate = trader.get_winrate()
        self.assertEqual(winrate, 50.0)  # 1 из 2 прибыльных

    def test_unique_constraint(self):
        """Тест уникального ограничения."""
        # Создаем первого трейдера
        Trader.objects.create(
            exchange_client=self.exchange_client,
            trading_pair=self.trading_pair,
            timeframe=Timeframe.ONE_MINUTE,
            strategy=self.strategy,
            risk_manager=self.risk_manager,
        )

        # Попытка создать дублирующегося трейдера должна вызвать ошибку
        with self.assertRaises(Exception):  # IntegrityError в реальной БД
            Trader.objects.create(
                exchange_client=self.exchange_client,
                trading_pair=self.trading_pair,
                timeframe=Timeframe.ONE_MINUTE,
                strategy=self.strategy,
                risk_manager=self.risk_manager,
            )

    def test_trader_instantiate(self):
        """Тест создания доменного объекта трейдера."""
        trader = Trader.objects.create(
            exchange_client=self.exchange_client,
            trading_pair=self.trading_pair,
            timeframe=Timeframe.ONE_MINUTE,
            strategy=self.strategy,
            risk_manager=self.risk_manager,
            initial_balance=Decimal("1000.00"),
            max_drawdown_pct=Decimal("10.00"),
            max_positions_count=3,
        )

        domain_trader = trader.instantiate()

        self.assertEqual(domain_trader.trading_pair.name, trader.trading_pair.name)
        self.assertEqual(domain_trader.initial_balance, trader.initial_balance)
        self.assertEqual(domain_trader.max_drawdown_pct, trader.max_drawdown_pct)
        self.assertEqual(domain_trader.max_positions_count, trader.max_positions_count)
