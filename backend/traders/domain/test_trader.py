"""
Тесты для доменной логики трейдера.
"""
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

from exchanges.domain.schemas import (
    Candle,
    OrderSide,
    OrderStatus,
    Timeframe,
    TradingPair,
)
from risk_managers.domain import (
    AbstractRiskManager,
    PositionType,
    PositionStatus,
    TraderPosition,
)
from strategies.domain import AbstractStrategy, SignalType, TraderSignal

from .traders import Trader


class TestTrader(unittest.TestCase):
    """Тесты для класса Trader."""

    def setUp(self):
        """Настройка тестового окружения."""
        # Мокаем зависимости
        self.mock_exchange_client = Mock()
        self.mock_exchange_client.create_market_order.return_value = {
            "amount": Decimal("0.1"),
            "price": Decimal("50000"),
            "status": "filled",  # Используем строку вместо OrderStatus.FILLED
            "timestamp": datetime.now(timezone.utc),
        }

        self.mock_strategy = Mock(spec=AbstractStrategy)
        self.mock_risk_manager = Mock(spec=AbstractRiskManager)

        # Создаем базовые объекты
        self.trading_pair = TradingPair(name="BTC/USDT", symbol="BTCUSDT")
        self.timeframe = Timeframe.ONE_MINUTE

        # Создаем трейдера
        self.trader = Trader(
            exchange_client=self.mock_exchange_client,
            trading_pair=self.trading_pair,
            timeframe=self.timeframe,
            strategy=self.mock_strategy,
            risk_manager=self.mock_risk_manager,
            initial_balance=Decimal("1000"),
            max_drawdown_pct=Decimal("10"),
            max_positions_count=3,
            current_balance=Decimal("1000"),
            trail_stop_enabled=False,
        )

    def test_trader_initialization(self):
        """Тест инициализации трейдера."""
        self.assertEqual(self.trader.initial_balance, Decimal("1000"))
        self.assertEqual(self.trader.current_balance, Decimal("1000"))
        self.assertEqual(self.trader.max_drawdown_pct, Decimal("10"))
        self.assertEqual(self.trader.max_positions_count, 3)
        self.assertFalse(self.trader.trail_stop_enabled)
        self.assertEqual(len(self.trader.signals), 0)
        self.assertEqual(len(self.trader.candles), 0)
        self.assertEqual(len(self.trader.orders), 0)
        self.assertEqual(len(self.trader.positions), 0)

    def test_create_market_order_buy(self):
        """Тест создания рыночного ордера на покупку."""
        timestamp = datetime.now(timezone.utc)
        order = self.trader.create_market_order(
            side=OrderSide.BUY,
            amount=Decimal("0.1"),
            price=Decimal("50000"),
            timestamp=timestamp,
        )

        self.assertEqual(order.side, OrderSide.BUY)
        self.assertEqual(order.amount, Decimal("0.1"))
        self.assertEqual(order.price, Decimal("50000"))
        self.assertEqual(order.status, "filled")
        self.assertEqual(len(self.trader.orders), 1)
        self.mock_exchange_client.create_market_order.assert_called_once()

    def test_create_market_order_sell(self):
        """Тест создания рыночного ордера на продажу."""
        timestamp = datetime.now(timezone.utc)
        order = self.trader.create_market_order(
            side=OrderSide.SELL,
            amount=Decimal("0.1"),
            price=Decimal("50000"),
            timestamp=timestamp,
        )

        self.assertEqual(order.side, OrderSide.SELL)
        self.assertEqual(order.amount, Decimal("0.1"))
        self.assertEqual(order.price, Decimal("50000"))
        self.assertEqual(len(self.trader.orders), 1)

    def test_can_open_position_with_valid_signal(self):
        """Тест проверки возможности открытия позиции с валидным сигналом."""
        # Настраиваем мок для проверки лимита просадки
        self.trader.check_drawdown_limit = Mock(return_value=True)
        
        # Тестируем сигнал BUY
        result = self.trader.can_open_position(
            SignalType.BUY, Decimal("50000")
        )
        self.assertTrue(result)

        # Тестируем сигнал SELL
        result = self.trader.can_open_position(
            SignalType.SELL, Decimal("50000")
        )
        self.assertTrue(result)

    def test_can_open_position_with_invalid_signal(self):
        """Тест проверки возможности открытия позиции с невалидным сигналом."""
        result = self.trader.can_open_position(
            SignalType.WAIT, Decimal("50000")
        )
        self.assertFalse(result)

    def test_can_open_position_with_drawdown_limit_exceeded(self):
        """Тест проверки возможности открытия позиции
        при превышении лимита просадки."""
        # Настраиваем мок для проверки лимита просадки
        self.trader.check_drawdown_limit = Mock(return_value=False)
        
        result = self.trader.can_open_position(
            SignalType.BUY, Decimal("50000")
        )
        self.assertFalse(result)

    def test_opened_positions_property(self):
        """Тест свойства opened_positions."""
        # Добавляем открытую позицию
        opened_position = TraderPosition(
            type=PositionType.LONG,
            status=PositionStatus.OPENED,
            amount=Decimal("0.1"),
            open_price=Decimal("50000"),
            opened_at=datetime.now(timezone.utc),
        )
        
        # Добавляем закрытую позицию
        closed_position = TraderPosition(
            type=PositionType.LONG,
            status=PositionStatus.CLOSED,
            amount=Decimal("0.1"),
            open_price=Decimal("50000"),
            close_price=Decimal("55000"),
            opened_at=datetime.now(timezone.utc),
            closed_at=datetime.now(timezone.utc),
        )

        self.trader.positions = [opened_position, closed_position]
        
        opened_positions = list(self.trader.opened_positions)
        self.assertEqual(len(opened_positions), 1)
        self.assertEqual(opened_positions[0].status, PositionStatus.OPENED)

    def test_handle_candle_integration(self):
        """Интеграционный тест обработки свечи."""
        # Настраиваем стратегию для возврата сигнала BUY
        self.mock_strategy.get_signal.return_value = SignalType.BUY
        self.mock_strategy.handle_candle = Mock()
        
        # Настраиваем риск-менеджер
        self.mock_risk_manager.calculate_position_size.return_value = Decimal("0.1")
        self.mock_risk_manager.get_stop_loss.return_value = Decimal("45000")
        self.mock_risk_manager.get_take_profit.return_value = Decimal("55000")
        
        # Настраиваем проверку лимита просадки
        self.trader.check_drawdown_limit = Mock(return_value=True)
        
        # Создаем тестовую свечу
        candle = Candle(
            timestamp=datetime.now(timezone.utc),
            open=Decimal("49000"),
            high=Decimal("51000"),
            low=Decimal("48000"),
            close=Decimal("50000"),
            volume=Decimal("100"),
        )

        # Обрабатываем свечу
        self.trader.handle_candle(candle, create_order=True)

        # Проверяем, что стратегия была вызвана
        self.mock_strategy.handle_candle.assert_called_once_with(candle=candle)
        self.mock_strategy.get_signal.assert_called_once()
        
        # Проверяем, что свеча добавлена
        self.assertEqual(len(self.trader.candles), 1)
        self.assertEqual(self.trader.candles[0], candle)

    def test_load_and_dump_state(self):
        """Тест загрузки и сохранения состояния."""
        # Добавляем тестовые данные
        test_signal = TraderSignal(
            timestamp=datetime.now(timezone.utc),
            type=SignalType.BUY,
            price=Decimal("50000"),
        )
        self.trader.signals.append(test_signal)
        
        # Настраиваем моки для загрузки/сохранения состояния
        self.mock_strategy.load_state = Mock()
        self.mock_strategy.dump_state = Mock(
            return_value={"strategy_data": "test"}
        )
        self.mock_risk_manager.load_state = Mock()
        self.mock_risk_manager.dump_state = Mock(
            return_value={"risk_data": "test"}
        )

        # Тестируем сохранение состояния
        state = self.trader.dump_state()
        self.assertIn("strategy", state)
        self.assertIn("risk_manager", state)
        self.assertIn("signals", state)
        
        # Тестируем загрузку состояния
        self.trader.load_state(state)
        self.mock_strategy.load_state.assert_called_once()
        self.mock_risk_manager.load_state.assert_called_once()

    def test_check_opened_positions_with_stop_loss(self):
        """Тест проверки открытых позиций со стоп-лоссом."""
        # Создаем открытую позицию
        position = TraderPosition(
            type=PositionType.LONG,
            status=PositionStatus.OPENED,
            amount=Decimal("0.1"),
            open_price=Decimal("50000"),
            stop_loss=Decimal("45000"),
            opened_at=datetime.now(timezone.utc),
        )
        self.trader.positions = [position]
        
        # Создаем свечу с ценой ниже стоп-лосса
        candle = Candle(
            timestamp=datetime.now(timezone.utc),
            open=Decimal("44000"),
            high=Decimal("44500"),
            low=Decimal("43000"),
            close=Decimal("44000"),
            volume=Decimal("100"),
        )

        # Настраиваем мок для should_be_closed
        position.should_be_closed = Mock(return_value=True)
        
        # Проверяем открытые позиции
        self.trader.check_opened_positions(candle, create_order=True)
        
        # Проверяем, что создан ордер на закрытие позиции
        self.assertEqual(len(self.trader.orders), 1)
        self.assertEqual(self.trader.orders[0].side, OrderSide.SELL)

    def test_maximum_positions_limit(self):
        """Тест ограничения максимального количества позиций."""
        # Создаем максимальное количество открытых позиций
        for i in range(self.trader.max_positions_count):
            position = TraderPosition(
                type=PositionType.LONG,
                status=PositionStatus.OPENED,
                amount=Decimal("0.1"),
                open_price=Decimal("50000"),
                opened_at=datetime.now(timezone.utc),
            )
            self.trader.positions.append(position)
        
        # Настраиваем стратегию для возврата сигнала BUY
        self.mock_strategy.get_signal.return_value = SignalType.BUY
        self.mock_strategy.handle_candle = Mock()
        
        # Настраиваем проверку лимита просадки
        self.trader.check_drawdown_limit = Mock(return_value=True)
        
        # Создаем свечу
        candle = Candle(
            timestamp=datetime.now(timezone.utc),
            open=Decimal("49000"),
            high=Decimal("51000"),
            low=Decimal("48000"),
            close=Decimal("50000"),
            volume=Decimal("100"),
        )

        initial_orders_count = len(self.trader.orders)
        
        # Обрабатываем свечу
        self.trader.handle_candle(candle, create_order=True)
        
        # Проверяем, что новые ордера не созданы из-за лимита позиций
        self.assertEqual(len(self.trader.orders), initial_orders_count)

    def test_drawdown_limit_calculation(self):
        """Тест расчета лимита просадки."""
        # Уменьшаем текущий баланс
        self.trader.current_balance = Decimal("850")  # 15% просадка
        
        # Тестируем проверку лимита просадки
        result = self.trader.check_drawdown_limit(
            self.trader.current_balance,
            self.trader.initial_balance
        )
        
        # При просадке 15% и лимите 10% должен вернуть False
        self.assertFalse(result)
        
        # Тестируем с допустимой просадкой
        self.trader.current_balance = Decimal("950")  # 5% просадка
        result = self.trader.check_drawdown_limit(
            self.trader.current_balance,
            self.trader.initial_balance
        )
        
        # При просадке 5% и лимите 10% должен вернуть True
        self.assertTrue(result)


class TestTraderIntegration(unittest.TestCase):
    """Интеграционные тесты трейдера."""

    def setUp(self):
        """Настройка интеграционного тестового окружения."""
        # Создаем реальные моки с более детальным поведением
        self.mock_exchange_client = Mock()
        self.mock_strategy = Mock(spec=AbstractStrategy)
        self.mock_risk_manager = Mock(spec=AbstractRiskManager)

        self.trading_pair = TradingPair(name="BTC/USDT", symbol="BTCUSDT")
        self.timeframe = Timeframe.ONE_MINUTE

        self.trader = Trader(
            exchange_client=self.mock_exchange_client,
            trading_pair=self.trading_pair,
            timeframe=self.timeframe,
            strategy=self.mock_strategy,
            risk_manager=self.mock_risk_manager,
            initial_balance=Decimal("1000"),
            max_drawdown_pct=Decimal("10"),
            max_positions_count=2,
            current_balance=Decimal("1000"),
        )

    def test_full_trading_cycle(self):
        """Тест полного торгового цикла: открытие и закрытие позиции."""
        # Этап 1: Получение сигнала на покупку
        self.mock_strategy.get_signal.return_value = SignalType.BUY
        self.mock_strategy.handle_candle = Mock()
        
        self.mock_risk_manager.calculate_position_size.return_value = Decimal("0.1")
        self.mock_risk_manager.get_stop_loss.return_value = Decimal("45000")
        self.mock_risk_manager.get_take_profit.return_value = Decimal("55000")
        
        self.mock_exchange_client.create_market_order.return_value = {
            "amount": Decimal("0.1"),
            "price": Decimal("50000"),
            "status": "filled",  # Используем строку вместо OrderStatus.FILLED
            "timestamp": datetime.now(timezone.utc),
        }
        
        self.trader.check_drawdown_limit = Mock(return_value=True)

        # Создаем свечу для открытия позиции
        open_candle = Candle(
            timestamp=datetime.now(timezone.utc),
            open=Decimal("49000"),
            high=Decimal("51000"),
            low=Decimal("48000"),
            close=Decimal("50000"),
            volume=Decimal("100"),
        )

        # Обрабатываем свечу - должна открыться позиция
        self.trader.handle_candle(open_candle, create_order=True)
        
        # Проверяем, что позиция открылась
        self.assertEqual(len(self.trader.positions), 1)
        self.assertEqual(len(self.trader.orders), 1)
        self.assertEqual(self.trader.orders[0].side, OrderSide.BUY)
        
        # Этап 2: Получение сигнала на продажу
        self.mock_strategy.get_signal.return_value = SignalType.SELL
        
        # Создаем свечу для закрытия позиции
        close_candle = Candle(
            timestamp=datetime.now(timezone.utc),
            open=Decimal("55000"),
            high=Decimal("56000"),
            low=Decimal("54000"),
            close=Decimal("55000"),
            volume=Decimal("100"),
        )

        # Настраиваем позицию для закрытия
        position = self.trader.positions[0]
        position.should_be_closed = Mock(return_value=True)
        
        # Обрабатываем свечу - должна закрыться позиция
        self.trader.handle_candle(close_candle, create_order=True)
        
        # Проверяем, что создан ордер на продажу
        sell_orders = [order for order in self.trader.orders if order.side == OrderSide.SELL]
        self.assertEqual(len(sell_orders), 1)

    def test_multiple_signals_handling(self):
        """Тест обработки множественных сигналов."""
        signals = [SignalType.BUY, SignalType.WAIT, SignalType.SELL, SignalType.WAIT]
        expected_orders_count = 0
        
        self.mock_strategy.handle_candle = Mock()
        self.trader.check_drawdown_limit = Mock(return_value=True)
        
        self.mock_risk_manager.calculate_position_size.return_value = Decimal("0.1")
        self.mock_risk_manager.get_stop_loss.return_value = Decimal("45000")
        self.mock_risk_manager.get_take_profit.return_value = Decimal("55000")
        
        self.mock_exchange_client.create_market_order.return_value = {
            "amount": Decimal("0.1"),
            "price": Decimal("50000"),
            "status": "filled",  # Используем строку вместо OrderStatus.FILLED
            "timestamp": datetime.now(timezone.utc),
        }

        for i, signal in enumerate(signals):
            self.mock_strategy.get_signal.return_value = signal
            
            candle = Candle(
                timestamp=datetime.now(timezone.utc),
                open=Decimal("50000"),
                high=Decimal("51000"),
                low=Decimal("49000"),
                close=Decimal("50000"),
                volume=Decimal("100"),
            )
            
            self.trader.handle_candle(candle, create_order=True)
            
            # Увеличиваем счетчик ожидаемых ордеров только для BUY/SELL сигналов
            if signal in {SignalType.BUY, SignalType.SELL}:
                expected_orders_count += 1
            
            # Проверяем количество сигналов
            self.assertEqual(len(self.trader.signals), i + 1)
        
        # Проверяем общее количество ордеров
        self.assertEqual(len(self.trader.orders), expected_orders_count)


if __name__ == "__main__":
    unittest.main()
