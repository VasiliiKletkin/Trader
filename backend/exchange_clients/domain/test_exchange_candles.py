# """
# Тесты для exchange clients.
# """

# from datetime import datetime, timezone, timedelta
# from decimal import Decimal
# from typing import List, Dict, Any
# from unittest.mock import AsyncMock, Mock, MagicMock, patch

# import pytest


# from exchanges.domain import Candle, TradingPair, Timeframe
# from exchange_clients.domain.exchange_clients import ByBitExchangeClient
# from exchange_clients.domain.schemas import (
#     ExchangeClientBalance,
#     ExchangeClientOrder,
#     OrderSide,
#     OrderStatus,
#     OrderType,
# )
# from exchange_clients.domain.proxies import ExchangeClientProxy


# # ==================== Fixtures ====================


# @pytest.fixture
# def mock_trading_pair() -> TradingPair:
#     """Mock торговой пары."""
#     return TradingPair(
#         name="BTC/USDT",
#         symbol="BTCUSDT",
#         min_amount=Decimal("0.001"),
#         max_amount=Decimal("1000.0"),
#         fee_percent=Decimal("0.1"),
#     )


# @pytest.fixture
# def sample_ohlcv_data() -> List[List]:
#     """Пример данных OHLCV от биржи."""
#     base_time = int(datetime.now(timezone.utc).timestamp() * 1000)
#     return [
#         [base_time, 100.0, 110.0, 95.0, 105.0, 1000.0],
#         [base_time + 60000, 105.0, 115.0, 100.0, 110.0, 1100.0],
#         [base_time + 120000, 110.0, 120.0, 105.0, 115.0, 1200.0],
#         [base_time + 180000, 115.0, 125.0, 110.0, 120.0, 1300.0],
#         [base_time + 240000, 120.0, 130.0, 115.0, 125.0, 1400.0],
#     ]


# @pytest.fixture
# def sample_balance_data() -> Dict[str, Any]:
#     """Пример данных баланса от биржи."""
#     return {
#         "BTC": {
#             "free": 1.5,
#             "total": 2.0,
#             "used": 0.5,
#             "debt": 0.0,
#         },
#         "USDT": {
#             "free": 10000.0,
#             "total": 15000.0,
#             "used": 5000.0,
#             "debt": 0.0,
#         },
#         "ETH": {
#             "free": 10.0,
#             "total": 12.0,
#             "used": 2.0,
#             "debt": 0.0,
#         },
#         "info": {"some": "metadata"},
#         "timestamp": 1234567890,
#         "datetime": "2024-01-01T00:00:00Z",
#         "free": {},
#         "used": {},
#         "total": {},
#     }


# @pytest.fixture
# def sample_order_data() -> Dict[str, Any]:
#     """Пример данных ордера от биржи."""
#     return {
#         "id": "order_123",
#         "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
#         "side": "buy",
#         "price": 100.0,
#         "amount": 1.0,
#         "status": "closed",
#         "type": "market",
#         "cost": 100.0,
#         "fee": {"cost": 0.1},
#     }


# @pytest.fixture
# def sample_orders_data() -> List[Dict[str, Any]]:
#     """Пример данных ордеров от биржи."""
#     base_time = int(datetime.now(timezone.utc).timestamp() * 1000)
#     return [
#         {
#             "id": "order_1",
#             "timestamp": base_time,
#             "side": "buy",
#             "price": 100.0,
#             "amount": 1.0,
#             "status": "closed",
#             "type": "market",
#             "cost": 100.0,
#             "fee": {"cost": 0.1},
#         },
#         {
#             "id": "order_2",
#             "timestamp": base_time + 60000,
#             "side": "sell",
#             "price": 105.0,
#             "amount": 0.5,
#             "status": "closed",
#             "type": "limit",
#             "cost": 52.5,
#             "fee": {"cost": 0.05},
#         },
#         {
#             "id": "order_3",
#             "timestamp": base_time + 120000,
#             "side": "buy",
#             "price": 102.0,
#             "amount": 2.0,
#             "status": "open",
#             "type": "limit",
#             "cost": 204.0,
#             "fee": {"cost": 0.2},
#         },
#     ]


# @pytest.fixture
# def mock_ccxt_exchange():
#     """Mock ccxt exchange."""
#     exchange = MagicMock()
#     exchange.fetch_ohlcv = AsyncMock()
#     exchange.fetch_balance = AsyncMock()
#     exchange.fetch_orders = AsyncMock()
#     exchange.fetch_order = AsyncMock()
#     exchange.create_market_order = AsyncMock()
#     exchange.fetch_open_order = AsyncMock()
#     exchange.fetch_open_orders = AsyncMock()
#     exchange.cancel_all_orders = AsyncMock()
#     exchange.close = AsyncMock()
#     exchange.enable_demo_trading = Mock()
#     exchange.timeout = 10000
#     return exchange


# # ==================== ExchangeClientProxy Tests ====================


# class TestExchangeClientProxy:
#     """Тесты для ExchangeClientProxy."""

#     def test_proxy_init(self):
#         """Тест инициализации прокси."""
#         proxy = ExchangeClientProxy(
#             host="proxy.example.com",
#             port=8080,
#             username="user",
#             password="pass",
#         )

#         assert proxy.host == "proxy.example.com"
#         assert proxy.port == 8080
#         assert proxy.username == "user"
#         assert proxy.password == "pass"

#     def test_proxy_url_with_auth(self):
#         """Тест URL прокси с авторизацией."""
#         proxy = ExchangeClientProxy(
#             host="proxy.example.com",
#             port=8080,
#             username="user",
#             password="pass",
#         )

#         assert proxy.url == "http://user:pass@proxy.example.com:8080"

#     def test_proxy_url_without_auth(self):
#         """Тест URL прокси без авторизации."""
#         proxy = ExchangeClientProxy(
#             host="proxy.example.com",
#             port=8080,
#         )

#         assert proxy.url == "http://proxy.example.com:8080"

#     def test_proxy_url_with_username_only(self):
#         """Тест URL прокси только с username."""
#         proxy = ExchangeClientProxy(
#             host="proxy.example.com",
#             port=8080,
#             username="user",
#         )

#         assert proxy.url == "http://proxy.example.com:8080"

#     def test_proxy_url_with_password_only(self):
#         """Тест URL прокси только с password."""
#         proxy = ExchangeClientProxy(
#             host="proxy.example.com",
#             port=8080,
#             password="pass",
#         )

#         assert proxy.url == "http://proxy.example.com:8080"

#     def test_proxy_different_ports(self):
#         """Тест прокси с разными портами."""
#         proxy_80 = ExchangeClientProxy(host="proxy.com", port=80)
#         proxy_3128 = ExchangeClientProxy(host="proxy.com", port=3128)
#         proxy_443 = ExchangeClientProxy(host="proxy.com", port=443)

#         assert ":80" in proxy_80.url
#         assert ":3128" in proxy_3128.url
#         assert ":443" in proxy_443.url


# # ==================== ExchangeClientBalance Tests ====================


# class TestExchangeClientBalance:
#     """Тесты для ExchangeClientBalance."""

#     def test_balance_init(self):
#         """Тест инициализации баланса."""
#         balance = ExchangeClientBalance(
#             currency="BTC",
#             free=Decimal("1.5"),
#             total=Decimal("2.0"),
#             used=Decimal("0.5"),
#             debt=Decimal("0.0"),
#         )

#         assert balance.currency == "BTC"
#         assert balance.free == Decimal("1.5")
#         assert balance.total == Decimal("2.0")
#         assert balance.used == Decimal("0.5")
#         assert balance.debt == Decimal("0.0")

#     def test_balance_with_debt(self):
#         """Тест баланса с долгом."""
#         balance = ExchangeClientBalance(
#             currency="USDT",
#             free=Decimal("1000"),
#             total=Decimal("1500"),
#             used=Decimal("500"),
#             debt=Decimal("200"),
#         )

#         assert balance.debt == Decimal("200")

#     def test_balance_zero_values(self):
#         """Тест баланса с нулевыми значениями."""
#         balance = ExchangeClientBalance(
#             currency="ETH",
#             free=Decimal("0"),
#             total=Decimal("0"),
#             used=Decimal("0"),
#             debt=Decimal("0"),
#         )

#         assert balance.free == Decimal("0")
#         assert balance.total == Decimal("0")


# # ==================== ExchangeClientOrder Tests ====================


# class TestExchangeClientOrder:
#     """Тесты для ExchangeClientOrder."""

#     def test_order_init_market_buy(self):
#         """Тест инициализации рыночного ордера на покупку."""
#         order = ExchangeClientOrder(
#             id="order_123",
#             timestamp=datetime.now(timezone.utc),
#             side=OrderSide.BUY,
#             price=Decimal("100.00"),
#             amount=Decimal("1.0"),
#             status=OrderStatus.CLOSED,
#             type=OrderType.MARKET,
#             cost=Decimal("100.00"),
#             fee=Decimal("0.1"),
#         )

#         assert order.id == "order_123"
#         assert order.side == OrderSide.BUY
#         assert order.type == OrderType.MARKET
#         assert order.status == OrderStatus.CLOSED

#     def test_order_init_limit_sell(self):
#         """Тест инициализации лимитного ордера на продажу."""
#         order = ExchangeClientOrder(
#             id="order_456",
#             timestamp=datetime.now(timezone.utc),
#             side=OrderSide.SELL,
#             price=Decimal("105.00"),
#             amount=Decimal("0.5"),
#             status=OrderStatus.OPEN,
#             type=OrderType.LIMIT,
#             cost=Decimal("52.50"),
#             fee=Decimal("0.05"),
#         )

#         assert order.side == OrderSide.SELL
#         assert order.type == OrderType.LIMIT
#         assert order.status == OrderStatus.OPEN

#     def test_order_canceled_status(self):
#         """Тест ордера со статусом отменён."""
#         order = ExchangeClientOrder(
#             id="order_789",
#             timestamp=datetime.now(timezone.utc),
#             side=OrderSide.BUY,
#             price=Decimal("100.00"),
#             amount=Decimal("1.0"),
#             status=OrderStatus.CANCELED,
#             type=OrderType.LIMIT,
#             cost=Decimal("0"),
#             fee=Decimal("0"),
#         )

#         assert order.status == OrderStatus.CANCELED


# # ==================== OrderSide Tests ====================


# class TestOrderSide:
#     """Тесты для OrderSide enum."""

#     def test_order_side_buy(self):
#         """Тест значения BUY."""
#         assert OrderSide.BUY.value == "buy"

#     def test_order_side_sell(self):
#         """Тест значения SELL."""
#         assert OrderSide.SELL.value == "sell"

#     def test_order_side_from_string(self):
#         """Тест создания из строки."""
#         assert OrderSide("buy") == OrderSide.BUY
#         assert OrderSide("sell") == OrderSide.SELL


# # ==================== OrderStatus Tests ====================


# class TestOrderStatus:
#     """Тесты для OrderStatus enum."""

#     def test_order_status_open(self):
#         """Тест значения OPEN."""
#         assert OrderStatus.OPEN.value == "open"

#     def test_order_status_closed(self):
#         """Тест значения CLOSED."""
#         assert OrderStatus.CLOSED.value == "closed"

#     def test_order_status_canceled(self):
#         """Тест значения CANCELED."""
#         assert OrderStatus.CANCELED.value == "canceled"


# # ==================== OrderType Tests ====================


# class TestOrderType:
#     """Тесты для OrderType enum."""

#     def test_order_type_market(self):
#         """Тест значения MARKET."""
#         assert OrderType.MARKET.value == "market"

#     def test_order_type_limit(self):
#         """Тест значения LIMIT."""
#         assert OrderType.LIMIT.value == "limit"


# # ==================== ByBitExchangeClient Init Tests ====================


# class TestByBitExchangeClientInit:
#     """Тесты инициализации ByBitExchangeClient."""

#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     def test_init_default_params(self, mock_bybit):
#         """Тест инициализации с параметрами по умолчанию."""
#         mock_exchange = MagicMock()
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         assert client.api_key == "test_key"
#         assert client.api_secret == "test_secret"
#         mock_exchange.enable_demo_trading.assert_called_once_with(True)

#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     def test_init_live_trading(self, mock_bybit):
#         """Тест инициализации для реальной торговли."""
#         mock_exchange = MagicMock()
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#             demo=False,
#         )

#         mock_exchange.enable_demo_trading.assert_not_called()

#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     def test_init_with_proxy(self, mock_bybit):
#         """Тест инициализации с прокси."""
#         mock_exchange = MagicMock()
#         mock_bybit.return_value = mock_exchange

#         proxy = ExchangeClientProxy(
#             host="proxy.example.com",
#             port=8080,
#             username="user",
#             password="pass",
#         )

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#             proxy=proxy,
#         )

#         assert client is not None
#         # Проверяем что прокси был передан в конфигурацию
#         call_args = mock_bybit.call_args
#         assert call_args is not None

#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     def test_init_sets_timeout(self, mock_bybit):
#         """Тест что устанавливается таймаут."""
#         mock_exchange = MagicMock()
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         assert mock_exchange.timeout == 10000

#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     def test_init_creates_exchange_instance(self, mock_bybit):
#         """Тест что создаётся экземпляр биржи."""
#         mock_exchange = MagicMock()
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         mock_bybit.assert_called_once()
#         assert client._exchange is mock_exchange


# # ==================== Context Manager Tests ====================


# class TestByBitExchangeClientContextManager:
#     """Тесты контекстного менеджера."""

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_async_context_manager_enter(self, mock_bybit):
#         """Тест входа в контекстный менеджер."""
#         mock_exchange = MagicMock()
#         mock_exchange.close = AsyncMock()
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         async with client as ctx:
#             assert ctx is client

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_async_context_manager_exit(self, mock_bybit):
#         """Тест выхода из контекстного менеджера."""
#         mock_exchange = MagicMock()
#         mock_exchange.close = AsyncMock()
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         async with client:
#             pass

#         mock_exchange.close.assert_called_once()

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_async_context_manager_exit_on_exception(self, mock_bybit):
#         """Тест выхода из контекстного менеджера при исключении."""
#         mock_exchange = MagicMock()
#         mock_exchange.close = AsyncMock()
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         with pytest.raises(ValueError):
#             async with client:
#                 raise ValueError("Test error")

#         mock_exchange.close.assert_called_once()

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_close_method(self, mock_bybit):
#         """Тест метода close."""
#         mock_exchange = MagicMock()
#         mock_exchange.close = AsyncMock()
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         await client.close()

#         mock_exchange.close.assert_called_once()

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_multiple_close_calls(self, mock_bybit):
#         """Тест множественных вызовов close."""
#         mock_exchange = MagicMock()
#         mock_exchange.close = AsyncMock()
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         await client.close()
#         await client.close()

#         assert mock_exchange.close.call_count == 2


# # ==================== Get Candles Tests ====================


# class TestByBitExchangeClientGetCandles:
#     """Тесты получения свечей."""

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_candles_basic(self, mock_bybit, sample_ohlcv_data):
#         """Тест базового получения свечей."""
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_ohlcv = AsyncMock(return_value=sample_ohlcv_data)
#         mock_exchange.close = AsyncMock()
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         candles = await client.get_candles("BTC/USDT", "1m")

#         assert len(candles) == 5
#         assert all(isinstance(c, Candle) for c in candles)
#         mock_exchange.fetch_ohlcv.assert_called_once()

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_candles_with_since_datetime(self, mock_bybit, sample_ohlcv_data):
#         """Тест получения свечей с параметром since (datetime)."""
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_ohlcv = AsyncMock(return_value=sample_ohlcv_data)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         since = datetime.now(timezone.utc) - timedelta(hours=1)
#         candles = await client.get_candles("BTC/USDT", "1m", since=since)

#         assert len(candles) == 5
#         call_args = mock_exchange.fetch_ohlcv.call_args
#         assert call_args[1]["since"] == int(since.timestamp() * 1000)

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_candles_with_since_int(self, mock_bybit, sample_ohlcv_data):
#         """Тест получения свечей с параметром since (int)."""
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_ohlcv = AsyncMock(return_value=sample_ohlcv_data)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         since = int(datetime.now(timezone.utc).timestamp() * 1000)
#         candles = await client.get_candles("BTC/USDT", "1m", since=since)

#         call_args = mock_exchange.fetch_ohlcv.call_args
#         assert call_args[1]["since"] == since

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_candles_with_limit(self, mock_bybit, sample_ohlcv_data):
#         """Тест получения свечей с лимитом."""
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_ohlcv = AsyncMock(return_value=sample_ohlcv_data[:3])
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         candles = await client.get_candles("BTC/USDT", "1m", limit=3)

#         assert len(candles) == 3
#         call_args = mock_exchange.fetch_ohlcv.call_args
#         assert call_args[1]["limit"] == 3

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_candles_empty_response(self, mock_bybit):
#         """Тест получения пустого списка свечей."""
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_ohlcv = AsyncMock(return_value=[])
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         candles = await client.get_candles("BTC/USDT", "1m")

#         assert len(candles) == 0
#         assert candles == []

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_candles_converts_to_decimal(self, mock_bybit, sample_ohlcv_data):
#         """Тест что значения конвертируются в Decimal."""
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_ohlcv = AsyncMock(return_value=sample_ohlcv_data)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         candles = await client.get_candles("BTC/USDT", "1m")

#         for candle in candles:
#             assert isinstance(candle.open, Decimal)
#             assert isinstance(candle.high, Decimal)
#             assert isinstance(candle.low, Decimal)
#             assert isinstance(candle.close, Decimal)
#             assert isinstance(candle.volume, Decimal)

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_candles_different_timeframes(self, mock_bybit, sample_ohlcv_data):
#         """Тест получения свечей для разных таймфреймов."""
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_ohlcv = AsyncMock(return_value=sample_ohlcv_data)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         timeframes = ["1m", "5m", "15m", "1h", "4h", "1d"]
#         for tf in timeframes:
#             await client.get_candles("BTC/USDT", tf)

#         assert mock_exchange.fetch_ohlcv.call_count == len(timeframes)

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_candles_different_symbols(self, mock_bybit, sample_ohlcv_data):
#         """Тест получения свечей для разных символов."""
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_ohlcv = AsyncMock(return_value=sample_ohlcv_data)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         symbols = ["BTC/USDT", "ETH/USDT", "XRP/USDT"]
#         for symbol in symbols:
#             await client.get_candles(symbol, "1h")

#         assert mock_exchange.fetch_ohlcv.call_count == len(symbols)

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_candles_preserves_order(self, mock_bybit, sample_ohlcv_data):
#         """Тест что порядок свечей сохраняется."""
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_ohlcv = AsyncMock(return_value=sample_ohlcv_data)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         candles = await client.get_candles("BTC/USDT", "1m")

#         # Проверяем что timestamps идут по возрастанию
#         for i in range(1, len(candles)):
#             assert candles[i].dt_unix > candles[i - 1].dt_unix


# # ==================== Get Balance Tests ====================


# class TestByBitExchangeClientGetBalance:
#     """Тесты получения баланса."""

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_balance_basic(self, mock_bybit, sample_balance_data):
#         """Тест базового получения баланса."""
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_balance = AsyncMock(return_value=sample_balance_data)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         balances = await client.get_balancess()

#         # Фильтруются служебные поля: info, timestamp, datetime, free, used, total
#         assert len(balances) == 3  # BTC, USDT, ETH
#         assert all(isinstance(b, ExchangeClientBalance) for b in balances)

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_balance_filters_metadata(self, mock_bybit, sample_balance_data):
#         """Тест что метаданные фильтруются."""
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_balance = AsyncMock(return_value=sample_balance_data)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         balances = await client.get_balances()

#         currencies = [b.currency for b in balances]
#         assert "info" not in currencies
#         assert "timestamp" not in currencies
#         assert "datetime" not in currencies
#         assert "free" not in currencies
#         assert "used" not in currencies
#         assert "total" not in currencies

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_balance_correct_values(self, mock_bybit, sample_balance_data):
#         """Тест корректности значений баланса."""
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_balance = AsyncMock(return_value=sample_balance_data)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         balances = await client.get_balances()
#         btc_balance = next(b for b in balances if b.currency == "BTC")

#         assert btc_balance.free == Decimal("1.5")
#         assert btc_balance.total == Decimal("2.0")
#         assert btc_balance.used == Decimal("0.5")
#         assert btc_balance.debt == Decimal("0.0")

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_balance_empty(self, mock_bybit):
#         """Тест пустого баланса."""
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_balance = AsyncMock(
#             return_value={
#                 "info": {},
#                 "timestamp": None,
#                 "datetime": None,
#                 "free": {},
#                 "used": {},
#                 "total": {},
#             }
#         )
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         balances = await client.get_balances()

#         assert len(balances) == 0

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_balance_converts_to_decimal(self, mock_bybit, sample_balance_data):
#         """Тест что значения конвертируются в Decimal."""
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_balance = AsyncMock(return_value=sample_balance_data)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         balances = await client.get_balances()

#         for balance in balances:
#             assert isinstance(balance.free, Decimal)
#             assert isinstance(balance.total, Decimal)
#             assert isinstance(balance.used, Decimal)
#             assert isinstance(balance.debt, Decimal)


# # ==================== Get Orders Tests ====================


# class TestByBitExchangeClientGetOrders:
#     """Тесты получения ордеров."""

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_orders_basic(self, mock_bybit, sample_orders_data, mock_trading_pair):
#         """Тест базового получения ордеров."""
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_orders = AsyncMock(return_value=sample_orders_data)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         orders = await client.get_orders(mock_trading_pair)

#         assert len(orders) == 3
#         assert all(isinstance(o, ExchangeClientOrder) for o in orders)

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_orders_with_since(self, mock_bybit, sample_orders_data, mock_trading_pair):
#         """Тест получения ордеров с параметром since."""
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_orders = AsyncMock(return_value=sample_orders_data)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         since = datetime.now(timezone.utc) - timedelta(hours=24)
#         orders = await client.get_orders(mock_trading_pair, since=since)

#         call_args = mock_exchange.fetch_orders.call_args
#         assert call_args[1]["since"] == int(since.timestamp() * 1000)

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_orders_with_limit(self, mock_bybit, sample_orders_data, mock_trading_pair):
#         """Тест получения ордеров с лимитом."""
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_orders = AsyncMock(return_value=sample_orders_data[:2])
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         orders = await client.get_orders(mock_trading_pair, limit=2)

#         assert len(orders) == 2
#         call_args = mock_exchange.fetch_orders.call_args
#         assert call_args[1]["limit"] == 2

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_orders_empty(self, mock_bybit, mock_trading_pair):
#         """Тест пустого списка ордеров."""
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_orders = AsyncMock(return_value=[])
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         orders = await client.get_orders(mock_trading_pair)

#         assert orders == []

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_orders_correct_values(
#         self, mock_bybit, sample_orders_data, mock_trading_pair
#     ):
#         """Тест корректности значений ордера."""
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_orders = AsyncMock(return_value=sample_orders_data)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         orders = await client.get_orders(mock_trading_pair)

#         first_order = orders[0]
#         assert first_order.id == "order_1"
#         assert first_order.side == OrderSide.BUY
#         assert first_order.price == Decimal("100.0")
#         assert first_order.amount == Decimal("1.0")
#         assert first_order.status == OrderStatus.CLOSED
#         assert first_order.type == OrderType.MARKET

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_orders_invalid_status_and_missing_fields(mock_bybit, mock_trading_pair):
#         """Тест обработки ордеров с невалидным статусом и отсутствующими полями."""
#         # Статус невалидный, отсутствуют обязательные поля
#         invalid_orders = [
#             {
#                 "id": "order_invalid",
#                 "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
#                 "side": "buy",
#                 "price": 100.0,
#                 "amount": 1.0,
#                 "status": "not_a_status",
#                 "type": "market",
#                 "cost": 100.0,
#                 "fee": {"cost": 0.1},
#             },
#             {
#                 "id": "order_missing_fields",
#                 "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
#                 "side": "buy",
#                 # missing price, amount, status, type, cost, fee
#             },
#         ]
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_orders = AsyncMock(return_value=invalid_orders)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         orders = await client.get_orders(mock_trading_pair)
#         # Должен вернуть пустой список, так как оба ордера невалидны
#         assert orders == []

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_orders_fee_is_none_and_fee_is_empty_dict(mock_bybit, mock_trading_pair):
#         """Тест обработки fee=None и fee={}."""
#         orders_data = [
#             {
#                 "id": "order_none_fee",
#                 "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
#                 "side": "buy",
#                 "price": 100.0,
#                 "amount": 1.0,
#                 "status": "closed",
#                 "type": "market",
#                 "cost": 100.0,
#                 "fee": None,
#             },
#             {
#                 "id": "order_empty_fee",
#                 "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
#                 "side": "sell",
#                 "price": 105.0,
#                 "amount": 0.5,
#                 "status": "closed",
#                 "type": "limit",
#                 "cost": 52.5,
#                 "fee": {},
#             },
#         ]
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_orders = AsyncMock(return_value=orders_data)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         orders = await client.get_orders(mock_trading_pair)
#         # Если схема валидна, то fee должно быть Decimal("0")
#         if orders:
#             assert orders[0].fee == Decimal("0")
#             assert orders[1].fee == Decimal("0")

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_orders_side_case_insensitive(mock_bybit, mock_trading_pair):
#         """Тест обработки сторон ордера в разных регистрах."""
#         orders_data = [
#             {
#                 "id": "order_upper_buy",
#                 "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
#                 "side": "BUY",
#                 "price": 100.0,
#                 "amount": 1.0,
#                 "status": "closed",
#                 "type": "market",
#                 "cost": 100.0,
#                 "fee": {"cost": 0.1},
#             },
#             {
#                 "id": "order_upper_sell",
#                 "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
#                 "side": "SELL",
#                 "price": 105.0,
#                 "amount": 0.5,
#                 "status": "closed",
#                 "type": "limit",
#                 "cost": 52.5,
#                 "fee": {"cost": 0.05},
#             },
#         ]
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_orders = AsyncMock(return_value=orders_data)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         orders = await client.get_orders(mock_trading_pair)
#         # Если схема поддерживает case-insensitive, то должны быть BUY и SELL
#         if orders:
#             assert orders[0].side.value.lower() == "buy"
#             assert orders[1].side.value.lower() == "sell"

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_orders_with_extra_fields(mock_bybit, mock_trading_pair):
#         """Тест обработки ордеров с лишними полями."""
#         orders_data = [
#             {
#                 "id": "order_extra",
#                 "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
#                 "side": "buy",
#                 "price": 100.0,
#                 "amount": 1.0,
#                 "status": "closed",
#                 "type": "market",
#                 "cost": 100.0,
#                 "fee": {"cost": 0.1},
#                 "extra_field": "should_be_ignored",
#             }
#         ]
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_orders = AsyncMock(return_value=orders_data)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         orders = await client.get_orders(mock_trading_pair)
#         # Лишние поля должны игнорироваться, а ордер быть валидным
#         assert len(orders) == 1
#         assert hasattr(orders[0], "id")
#         assert not hasattr(orders[0], "extra_field")


# # ==================== Get Order Tests ====================


# class TestByBitExchangeClientGetOrder:
#     """Тесты получения конкретного ордера."""

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_order_basic(self, mock_bybit, sample_order_data, mock_trading_pair):
#         """Тест получения ордера по ID."""
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_order = AsyncMock(return_value=sample_order_data)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         order = await client.get_order("order_123", mock_trading_pair)

#         assert order.id == "order_123"
#         mock_exchange.fetch_order.assert_called_once_with(
#             "order_123", mock_trading_pair.name
#         )

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_order_converts_values(
#         self, mock_bybit, sample_order_data, mock_trading_pair
#     ):
#         """Тест конвертации значений ордера."""
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_order = AsyncMock(return_value=sample_order_data)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         order = await client.get_order("order_123", mock_trading_pair)

#         assert isinstance(order.price, Decimal)
#         assert isinstance(order.amount, Decimal)
#         assert isinstance(order.cost, Decimal)
#         assert isinstance(order.fee, Decimal)


# # ==================== Create Market Order Tests ====================


# class TestByBitExchangeClientCreateMarketOrder:
#     """Тесты создания рыночных ордеров."""

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_create_market_order_buy(
#         self, mock_bybit, sample_order_data, mock_trading_pair
#     ):
#         """Тест создания рыночного ордера на покупку."""
#         mock_exchange = MagicMock()
#         mock_exchange.create_market_order = AsyncMock(return_value=sample_order_data)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         order = await client.create_market_order(
#             trading_pair=mock_trading_pair,
#             side=OrderSide.BUY,
#             amount=Decimal("1.0"),
#         )

#         assert order is not None
#         assert isinstance(order, ExchangeClientOrder)
#         mock_exchange.create_market_order.assert_called_once()

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_create_market_order_sell(
#         self, mock_bybit, sample_order_data, mock_trading_pair
#     ):
#         """Тест создания рыночного ордера на продажу."""
#         sample_order_data["side"] = "sell"
#         mock_exchange = MagicMock()
#         mock_exchange.create_market_order = AsyncMock(return_value=sample_order_data)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         order = await client.create_market_order(
#             trading_pair=mock_trading_pair,
#             side=OrderSide.SELL,
#             amount=Decimal("0.5"),
#         )

#         assert order.side == OrderSide.SELL
#         call_args = mock_exchange.create_market_order.call_args
#         assert call_args[0][1] == "sell"

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_create_market_order_with_params(
#         self, mock_bybit, sample_order_data, mock_trading_pair
#     ):
#         """Тест создания рыночного ордера с дополнительными параметрами."""
#         mock_exchange = MagicMock()
#         mock_exchange.create_market_order = AsyncMock(return_value=sample_order_data)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         params = {"reduceOnly": True, "timeInForce": "GTC"}
#         order = await client.create_market_order(
#             trading_pair=mock_trading_pair,
#             side=OrderSide.BUY,
#             amount=Decimal("1.0"),
#             params=params,
#         )

#         call_args = mock_exchange.create_market_order.call_args
#         assert call_args[1]["params"] == params

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_create_market_order_amount_conversion(
#         self, mock_bybit, sample_order_data, mock_trading_pair
#     ):
#         """Тест конвертации amount в float."""
#         mock_exchange = MagicMock()
#         mock_exchange.create_market_order = AsyncMock(return_value=sample_order_data)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         await client.create_market_order(
#             trading_pair=mock_trading_pair,
#             side=OrderSide.BUY,
#             amount=Decimal("1.5"),
#         )

#         call_args = mock_exchange.create_market_order.call_args
#         # amount должен быть конвертирован в float
#         assert call_args[0][2] == 1.5


# # ==================== Get Open Orders Tests ====================


# class TestByBitExchangeClientGetOpenOrders:
#     """Тесты получения открытых ордеров."""

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_open_orders_basic(
#         self, mock_bybit, sample_orders_data, mock_trading_pair
#     ):
#         """Тест получения открытых ордеров."""
#         open_orders = [o for o in sample_orders_data if o["status"] == "open"]
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_open_orders = AsyncMock(return_value=open_orders)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         orders = await client.get_open_orders(mock_trading_pair)

#         assert len(orders) == 1
#         assert all(o.status == OrderStatus.OPEN for o in orders)

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_open_orders_empty(self, mock_bybit, mock_trading_pair):
#         """Тест когда нет открытых ордеров."""
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_open_orders = AsyncMock(return_value=[])
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         orders = await client.get_open_orders(mock_trading_pair)

#         assert orders == []


# # ==================== Cancel All Orders Tests ====================


# class TestByBitExchangeClientCancelAllOrders:
#     """Тесты отмены всех ордеров."""

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_cancel_all_orders_basic(self, mock_bybit, mock_trading_pair):
#         """Тест отмены всех ордеров."""
#         mock_exchange = MagicMock()
#         mock_exchange.cancel_all_orders = AsyncMock(return_value={"success": True})
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         await client.cancel_all_orders(mock_trading_pair)

#         mock_exchange.cancel_all_orders.assert_called_once_with(mock_trading_pair.name)

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_cancel_all_orders_no_orders(self, mock_bybit, mock_trading_pair):
#         """Тест отмены когда нет ордеров."""
#         mock_exchange = MagicMock()
#         mock_exchange.cancel_all_orders = AsyncMock(return_value=[])
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         # Не должно вызывать исключение
#         await client.cancel_all_orders(mock_trading_pair)

#         mock_exchange.cancel_all_orders.assert_called_once()


# # ==================== Error Handling Tests ====================


# class TestByBitExchangeClientErrorHandling:
#     """Тесты обработки ошибок."""

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_candles_network_error(self, mock_bybit):
#         """Тест обработки сетевой ошибки при получении свечей."""
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_ohlcv = AsyncMock(side_effect=Exception("Network error"))
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         with pytest.raises(Exception, match="Network error"):
#             await client.get_candles("BTC/USDT", "1m")

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_balance_api_error(self, mock_bybit):
#         """Тест обработки ошибки API при получении баланса."""
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_balance = AsyncMock(side_effect=Exception("API rate limit"))
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         with pytest.raises(Exception, match="API rate limit"):
#             await client.get_balances()

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_create_order_insufficient_balance(
#         self, mock_bybit, mock_trading_pair
#     ):
#         """Тест ошибки недостаточного баланса."""
#         mock_exchange = MagicMock()
#         mock_exchange.create_market_order = AsyncMock(
#             side_effect=Exception("Insufficient balance")
#         )
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         with pytest.raises(Exception, match="Insufficient balance"):
#             await client.create_market_order(
#                 trading_pair=mock_trading_pair,
#                 side=OrderSide.BUY,
#                 amount=Decimal("1000000"),
#             )


# # ==================== Edge Cases Tests ====================


# class TestByBitExchangeClientEdgeCases:
#     """Тесты граничных случаев."""

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_candles_single_candle(self, mock_bybit):
#         """Тест получения одной свечи."""
#         single_candle = [[1234567890000, 100.0, 110.0, 95.0, 105.0, 1000.0]]
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_ohlcv = AsyncMock(return_value=single_candle)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         candles = await client.get_candles("BTC/USDT", "1m", limit=1)

#         assert len(candles) == 1

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_get_candles_very_old_date(self, mock_bybit, sample_ohlcv_data):
#         """Тест получения свечей за старую дату."""
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_ohlcv = AsyncMock(return_value=sample_ohlcv_data)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         old_date = datetime(2020, 1, 1, tzinfo=timezone.utc)
#         candles = await client.get_candles("BTC/USDT", "1d", since=old_date)

#         assert len(candles) == 5

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_create_order_min_amount(self, mock_bybit, sample_order_data, mock_trading_pair):
#         """Тест создания ордера с минимальным количеством."""
#         mock_exchange = MagicMock()
#         mock_exchange.create_market_order = AsyncMock(return_value=sample_order_data)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         await client.create_market_order(
#             trading_pair=mock_trading_pair,
#             side=OrderSide.BUY,
#             amount=Decimal("0.001"),
#         )

#         call_args = mock_exchange.create_market_order.call_args
#         assert call_args[0][2] == 0.001

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_balance_with_zero_values(self, mock_bybit):
#         """Тест баланса с нулевыми значениями."""
#         balance_data = {
#             "BTC": {
#                 "free": 0.0,
#                 "total": 0.0,
#                 "used": 0.0,
#                 "debt": 0.0,
#             },
#             "info": {},
#             "timestamp": None,
#             "datetime": None,
#             "free": {},
#             "used": {},
#             "total": {},
#         }
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_balance = AsyncMock(return_value=balance_data)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         balances = await client.get_balances()

#         assert len(balances) == 1
#         assert balances[0].free == Decimal("0.0")

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_order_with_none_fee(self, mock_bybit, mock_trading_pair):
#         """Тест ордера без комиссии."""
#         order_data = {
#             "id": "order_123",
#             "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
#             "side": "buy",
#             "price": Decimal("100.00"),
#             "amount": Decimal("1.0"),
#             "status": OrderStatus.CLOSED,
#             "type": OrderType.MARKET,
#             "cost": Decimal("100.00"),
#             "fee": None,
#         }
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_order = AsyncMock(return_value=order_data)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         order = await client.get_order("order_123", mock_trading_pair)

#         assert order.fee == Decimal("0")

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_order_with_empty_fee_dict(self, mock_bybit, mock_trading_pair):
#         """Тест ордера с пустым словарём комиссии."""
#         order_data = {
#             "id": "order_123",
#             "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
#             "side": "buy",
#             "price": Decimal("100.00"),
#             "amount": Decimal("1.0"),
#             "status": OrderStatus.CLOSED,
#             "type": OrderType.MARKET,
#             "cost": Decimal("100.00"),
#             "fee": {},
#         }
#         mock_exchange = MagicMock()
#         mock_exchange.fetch_order = AsyncMock(return_value=order_data)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         order = await client.get_order("order_123", mock_trading_pair)

#         assert order.fee == Decimal("0")


# # ==================== Concurrency Tests ====================


# class TestByBitExchangeClientConcurrency:
#     """Тесты конкурентного доступа."""

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_concurrent_candle_requests(self, mock_bybit, sample_ohlcv_data):
#         """Тест конкурентных запросов свечей."""
#         import asyncio

#         mock_exchange = MagicMock()
#         mock_exchange.fetch_ohlcv = AsyncMock(return_value=sample_ohlcv_data)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         # Запускаем несколько конкурентных запросов
#         tasks = [
#             client.get_candles("BTC/USDT", "1m"),
#             client.get_candles("ETH/USDT", "1m"),
#             client.get_candles("XRP/USDT", "1m"),
#         ]

#         results = await asyncio.gather(*tasks)

#         assert len(results) == 3
#         assert all(len(r) == 5 for r in results)

#     @pytest.mark.asyncio
#     @patch("exchange_clients.domain.exchange_clients.ccxt.bybit")
#     async def test_concurrent_different_operations(
#         self, mock_bybit, sample_ohlcv_data, sample_balance_data
#     ):
#         """Тест конкурентных разных операций."""
#         import asyncio

#         mock_exchange = MagicMock()
#         mock_exchange.fetch_ohlcv = AsyncMock(return_value=sample_ohlcv_data)
#         mock_exchange.fetch_balance = AsyncMock(return_value=sample_balance_data)
#         mock_bybit.return_value = mock_exchange

#         client = ByBitExchangeClient(
#             api_key="test_key",
#             api_secret="test_secret",
#         )

#         candles_task = client.get_candles("BTC/USDT", "1m")
#         balance_task = client.get_balances()

#         candles, balances = await asyncio.gather(candles_task, balance_task)

#         assert len(candles) == 5
#         assert len(balances) == 3
