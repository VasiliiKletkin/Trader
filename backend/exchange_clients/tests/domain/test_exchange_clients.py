"""
Тесты для доменной модели exchange_clients.
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from ccxt.base.errors import (
    AuthenticationError,
    ExchangeError,
    NetworkError,
    RateLimitExceeded,
)

from exchange_clients.domain import (
    ByBitExchangeClient,
    ExchangeClientBalance,
    ExchangeClientOrder,
    ExchangeClientProxy,
    OrderSide,
    OrderStatus,
    OrderType,
)
from exchanges.domain import Candle, Timeframe

# ==================== ExchangeClientProxy Tests ====================


class TestExchangeClientProxy:
    """Тесты для ExchangeClientProxy."""

    def test_proxy_init_default(self):
        """Тест инициализации прокси с протоколом по умолчанию."""
        proxy = ExchangeClientProxy(
            host="proxy.example.com",
            port="1080",
            username="user",
            password="pass",
        )

        assert proxy.protocol == "socks5"
        assert proxy.host == "proxy.example.com"
        assert proxy.port == "1080"
        assert proxy.username == "user"
        assert proxy.password == "pass"

    def test_proxy_init_custom_protocol(self):
        """Тест инициализации прокси с кастомным протоколом."""
        proxy = ExchangeClientProxy(
            protocol="http",
            host="proxy.example.com",
            port="8080",
            username="user",
            password="pass",
        )

        assert proxy.protocol == "http"

    def test_proxy_supports_different_protocols(self):
        """Тест поддержки различных протоколов."""
        protocols = ["http", "socks5", "socks4", "https"]

        for protocol in protocols:
            proxy = ExchangeClientProxy(
                protocol=protocol,
                host="proxy.example.com",
                port="1080",
                username="user",
                password="pass",
            )
            assert proxy.protocol == protocol


# ==================== ExchangeClientBalance Tests ====================


class TestExchangeClientBalance:
    """Тесты для ExchangeClientBalance."""

    def test_balance_init(self):
        """Тест инициализации баланса."""
        balance = ExchangeClientBalance(
            currency="BTC",
            total=Decimal("2.0"),
            free=Decimal("1.5"),
            used=Decimal("0.5"),
            debt=Decimal("0.0"),
        )

        assert balance.currency == "BTC"
        assert balance.total == Decimal("2.0")
        assert balance.free == Decimal("1.5")
        assert balance.used == Decimal("0.5")
        assert balance.debt == Decimal("0.0")

    def test_balance_with_debt(self):
        """Тест баланса с долгом."""
        balance = ExchangeClientBalance(
            currency="USDT",
            total=Decimal("1000.0"),
            free=Decimal("500.0"),
            used=Decimal("500.0"),
            debt=Decimal("100.0"),
        )

        assert balance.debt == Decimal("100.0")

    def test_balance_zero_values(self):
        """Тест баланса с нулевыми значениями."""
        balance = ExchangeClientBalance(
            currency="ETH",
            total=Decimal("0.0"),
            free=Decimal("0.0"),
            used=Decimal("0.0"),
            debt=Decimal("0.0"),
        )

        assert balance.total == Decimal("0.0")
        assert balance.free == Decimal("0.0")


# ==================== ExchangeClientOrder Tests ====================


class TestExchangeClientOrder:
    """Тесты для ExchangeClientOrder."""

    def test_order_init_buy(self, trading_pair):
        """Тест инициализации ордера на покупку."""
        order = ExchangeClientOrder(
            timestamp=datetime.now(UTC),
            status=OrderStatus.CLOSED,
            trading_pair=trading_pair,
            exchange_order_id="order_123",
            type=OrderType.MARKET,
            side=OrderSide.BUY,
            price=Decimal("29000.0"),
            amount=Decimal("0.1"),
            fee=Decimal("2.9"),
            cost=Decimal("2900.0"),
        )

        assert order.side == OrderSide.BUY
        assert order.type == OrderType.MARKET
        assert order.status == OrderStatus.CLOSED
        assert order.price == Decimal("29000.0")
        assert order.amount == Decimal("0.1")

    def test_order_init_sell(self, trading_pair):
        """Тест инициализации ордера на продажу."""
        order = ExchangeClientOrder(
            timestamp=datetime.now(UTC),
            status=OrderStatus.OPENED,
            trading_pair=trading_pair,
            exchange_order_id="order_456",
            type=OrderType.LIMIT,
            side=OrderSide.SELL,
            price=Decimal("30000.0"),
            amount=Decimal("0.05"),
            fee=Decimal("1.5"),
            cost=Decimal("1500.0"),
        )

        assert order.side == OrderSide.SELL
        assert order.type == OrderType.LIMIT
        assert order.status == OrderStatus.OPENED

    def test_order_with_id(self, trading_pair):
        """Тест ордера с ID."""
        order = ExchangeClientOrder(
            id=123,
            timestamp=datetime.now(UTC),
            status=OrderStatus.CLOSED,
            trading_pair=trading_pair,
            exchange_order_id="order_123",
            type=OrderType.MARKET,
            side=OrderSide.BUY,
            price=Decimal("29000.0"),
            amount=Decimal("0.1"),
            fee=Decimal("2.9"),
            cost=Decimal("2900.0"),
        )

        assert order.id == 123

    def test_order_without_id(self, trading_pair):
        """Тест ордера без ID (новый ордер)."""
        order = ExchangeClientOrder(
            timestamp=datetime.now(UTC),
            status=OrderStatus.OPENED,
            trading_pair=trading_pair,
            exchange_order_id="order_789",
            type=OrderType.MARKET,
            side=OrderSide.BUY,
            price=Decimal("29000.0"),
            amount=Decimal("0.1"),
            fee=Decimal("2.9"),
            cost=Decimal("2900.0"),
        )

        assert order.id is None

    def test_order_statuses(self, trading_pair):
        """Тест различных статусов ордера."""
        statuses = [OrderStatus.OPENED, OrderStatus.CLOSED, OrderStatus.CANCELED]

        for status in statuses:
            order = ExchangeClientOrder(
                timestamp=datetime.now(UTC),
                status=status,
                trading_pair=trading_pair,
                exchange_order_id="order_123",
                type=OrderType.MARKET,
                side=OrderSide.BUY,
                price=Decimal("29000.0"),
                amount=Decimal("0.1"),
                fee=Decimal("2.9"),
                cost=Decimal("2900.0"),
            )
            assert order.status == status


# ==================== ByBitExchangeClient Initialization Tests ====================


class TestByBitExchangeClientInit:
    """Тесты инициализации ByBitExchangeClient."""

    def test_init_stores_config(self, domain_exchange):
        """Тест что __init__ сохраняет конфигурацию и создаёт exchange."""
        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
            demo=False,
        )

        assert client.api_key == "test_key"
        assert client.api_secret == "test_secret"
        assert client.demo is False
        assert client.client is not None

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_init_demo_mode(
        self, mock_bybit_class, mock_ccxt_exchange, domain_exchange
    ):
        """Тест инициализации в demo режиме."""
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
            demo=True,
        )

        async with client:
            mock_ccxt_exchange.enable_demo_trading.assert_called_once_with(True)

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_init_production_mode(
        self, mock_bybit_class, mock_ccxt_exchange, domain_exchange
    ):
        """Тест инициализации в production режиме (demo=False)."""
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
            demo=False,
        )

        async with client:
            mock_ccxt_exchange.enable_demo_trading.assert_not_called()

    def test_init_with_proxy(self, exchange_client_proxy, domain_exchange):
        """Тест инициализации с прокси."""
        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
            demo=True,
            proxy=exchange_client_proxy,
        )

        assert client.api_key == "test_key"
        assert client.proxy == exchange_client_proxy

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_ccxt_config(
        self, mock_bybit_class, mock_ccxt_exchange, domain_exchange
    ):
        """Тест корректной конфигурации CCXT."""
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
        )

        async with client:
            mock_bybit_class.assert_called_once_with(
                {
                    "apiKey": "test_key",
                    "secret": "test_secret",
                    "enableRateLimit": True,
                }
            )


# ==================== ByBitExchangeClient Context Manager Tests ====================


class TestByBitExchangeClientContextManager:
    """Тесты контекстного менеджера."""

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_async_context_manager_enter(
        self, mock_bybit_class, mock_ccxt_exchange, domain_exchange
    ):
        """Тест входа в async контекстный менеджер."""
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
        )

        async with client as ctx_client:
            assert ctx_client == client

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_async_context_manager_delegates_to_exchange(
        self, mock_bybit_class, mock_ccxt_exchange, domain_exchange
    ):
        """Тест что контекстный менеджер делегирует в exchange."""
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
        )

        async with client:
            mock_ccxt_exchange.__aenter__.assert_called_once()

        mock_ccxt_exchange.__aexit__.assert_called_once()


# ==================== ByBitExchangeClient get_candles Tests ====================


class TestByBitExchangeClientGetCandles:
    """Тесты получения свечей."""

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_get_candles_success(
        self,
        mock_bybit_class,
        mock_ccxt_exchange,
        sample_ohlcv_data,
        trading_pair,
        domain_exchange,
    ):
        """Тест успешного получения свечей."""
        mock_ccxt_exchange.fetch_ohlcv.return_value = sample_ohlcv_data
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
        )

        async with client:
            candles = await client.fetch_candles(
                trading_pair=trading_pair,
                timeframe=Timeframe.ONE_HOUR,
                since=datetime(2021, 1, 1, tzinfo=UTC),
                limit=100,
            )

            assert len(candles) == 3
            assert all(isinstance(c, Candle) for c in candles)
            assert candles[0].dt_unix == 1609459200000
            assert candles[0].open == 29000.0
            assert candles[0].high == 29500.0
            assert candles[0].low == 28800.0
            assert candles[0].close == 29200.0
            assert candles[0].volume == 1500.0

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_get_candles_datetime_conversion(
        self,
        mock_bybit_class,
        mock_ccxt_exchange,
        sample_ohlcv_data,
        trading_pair,
        domain_exchange,
    ):
        """Тест конвертации datetime в timestamp."""
        mock_ccxt_exchange.fetch_ohlcv.return_value = sample_ohlcv_data
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
        )

        async with client:
            since_dt = datetime(2021, 1, 1, tzinfo=UTC)
            await client.fetch_candles(
                trading_pair=trading_pair,
                timeframe=Timeframe.ONE_HOUR,
                since=since_dt,
                limit=100,
            )

            expected_timestamp = int(since_dt.timestamp() * 1000)
            mock_ccxt_exchange.fetch_ohlcv.assert_called_once()
            call_args = mock_ccxt_exchange.fetch_ohlcv.call_args
            assert call_args[1]["since"] == expected_timestamp

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_get_candles_none_since(
        self,
        mock_bybit_class,
        mock_ccxt_exchange,
        sample_ohlcv_data,
        trading_pair,
        domain_exchange,
    ):
        """Тест получения свечей без параметра since."""
        mock_ccxt_exchange.fetch_ohlcv.return_value = sample_ohlcv_data
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
        )

        async with client:
            candles = await client.fetch_candles(
                trading_pair=trading_pair,
                timeframe=Timeframe.ONE_HOUR,
                since=None,
                limit=100,
            )

            assert len(candles) == 3
            mock_ccxt_exchange.fetch_ohlcv.assert_called_once()

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_get_candles_empty_result(
        self, mock_bybit_class, mock_ccxt_exchange, trading_pair, domain_exchange
    ):
        """Тест получения пустого списка свечей."""
        mock_ccxt_exchange.fetch_ohlcv.return_value = []
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
        )

        async with client:
            candles = await client.fetch_candles(
                trading_pair=trading_pair,
                timeframe=Timeframe.ONE_HOUR,
                limit=100,
            )

            assert len(candles) == 0

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_get_candles_with_params(
        self,
        mock_bybit_class,
        mock_ccxt_exchange,
        sample_ohlcv_data,
        trading_pair,
        domain_exchange,
    ):
        """Тест получения свечей с дополнительными параметрами."""
        mock_ccxt_exchange.fetch_ohlcv.return_value = sample_ohlcv_data
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
        )

        async with client:
            custom_params = {"category": "linear"}
            await client.fetch_candles(
                trading_pair=trading_pair,
                timeframe=Timeframe.ONE_HOUR,
                since=None,
                limit=100,
                params=custom_params,
            )

            call_args = mock_ccxt_exchange.fetch_ohlcv.call_args
            assert call_args[1]["params"] == custom_params


# ==================== ByBitExchangeClient get_balances Tests ====================


class TestByBitExchangeClientGetBalances:
    """Тесты получения балансов."""

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_get_balances_success(
        self, mock_bybit_class, mock_ccxt_exchange, sample_balance_data, domain_exchange
    ):
        """Тест успешного получения балансов."""
        mock_ccxt_exchange.fetch_balance.return_value = sample_balance_data
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
        )

        async with client:
            balances = await client.get_balances()

            assert len(balances) == 2  # BTC и USDT
            assert all(isinstance(b, ExchangeClientBalance) for b in balances)

            btc_balance = next(b for b in balances if b.currency == "BTC")
            assert btc_balance.free == Decimal("1.5")
            assert btc_balance.used == Decimal("0.5")
            assert btc_balance.total == Decimal("2.0")
            assert btc_balance.debt == Decimal("0.0")

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_get_balances_filters_invalid_entries(
        self, mock_bybit_class, mock_ccxt_exchange, domain_exchange
    ):
        """Тест фильтрации невалидных записей."""
        mock_ccxt_exchange.fetch_balance.return_value = {
            "BTC": {
                "free": 1.5,
                "used": 0.5,
                "total": 2.0,
                "debt": 0.0,
            },
            "info": {"some": "data"},  # Строка, не dict
            "timestamp": 1609459200000,  # Число, не dict
            "ETH": {
                "free": None,  # Невалидное значение
                "used": 0.5,
                "total": 2.0,
                "debt": 0.0,
            },
            "USDT": {
                # Отсутствует 'free' ключ
                "used": 2000.0,
                "total": 12000.0,
                "debt": 0.0,
            },
        }
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
        )

        async with client:
            balances = await client.get_balances()

            # Только BTC должен быть валидным
            assert len(balances) == 1
            assert balances[0].currency == "BTC"

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_get_balances_empty(
        self, mock_bybit_class, mock_ccxt_exchange, domain_exchange
    ):
        """Тест получения пустого списка балансов."""
        mock_ccxt_exchange.fetch_balance.return_value = {}
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
        )

        async with client:
            balances = await client.get_balances()

            assert len(balances) == 0

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_get_balances_with_params(
        self, mock_bybit_class, mock_ccxt_exchange, sample_balance_data, domain_exchange
    ):
        """Тест получения балансов с дополнительными параметрами."""
        mock_ccxt_exchange.fetch_balance.return_value = sample_balance_data
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
        )

        async with client:
            custom_params = {"accountType": "UNIFIED"}
            await client.get_balances(params=custom_params)

            mock_ccxt_exchange.fetch_balance.assert_called_once_with(
                params=custom_params
            )


# ==================== ByBitExchangeClient get_orders Tests ====================


class TestByBitExchangeClientGetOrders:
    """Тесты получения ордеров."""

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_get_orders_success(
        self, mock_bybit_class, mock_ccxt_exchange, trading_pair, domain_exchange
    ):
        """Тест успешного получения ордеров."""
        mock_ccxt_exchange.fetch_orders.return_value = [
            {
                "timestamp": 1609459200000,
                "side": "buy",
                "price": 29000.0,
                "amount": 0.1,
                "status": "closed",
            }
        ]
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
        )

        async with client:
            orders = await client.get_orders(
                trading_pair=trading_pair,
                since=1609459200000,
                limit=100,
            )

            # Метод get_orders заполняет недостающие поля значениями по умолчанию
            assert len(orders) == 1
            assert orders[0].side == OrderSide.BUY
            assert orders[0].price == Decimal("29000.0")

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_get_orders_empty(
        self, mock_bybit_class, mock_ccxt_exchange, trading_pair, domain_exchange
    ):
        """Тест получения пустого списка ордеров."""
        mock_ccxt_exchange.fetch_orders.return_value = []
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
        )

        async with client:
            orders = await client.get_orders(trading_pair=trading_pair)

            assert len(orders) == 0

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_get_orders_with_exception(
        self, mock_bybit_class, mock_ccxt_exchange, trading_pair, domain_exchange
    ):
        """Тест обработки исключения при получении ордеров."""
        mock_ccxt_exchange.fetch_orders.side_effect = ExchangeError("Exchange error")
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
        )

        async with client:
            orders = await client.get_orders(trading_pair=trading_pair)

            # При ошибке возвращается пустой список
            assert len(orders) == 0

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_get_orders_invalid_order_data(
        self, mock_bybit_class, mock_ccxt_exchange, trading_pair, domain_exchange
    ):
        """Тест пропуска невалидных данных ордера."""
        mock_ccxt_exchange.fetch_orders.return_value = [
            {
                "id": "order_1",
                "timestamp": 1609459200000,
                "side": "buy",
                "price": 29000.0,
                "amount": 0.1,
                "status": "closed",
            },
            {
                "timestamp": 1609459200000,  # Валидный ордер
                "side": "sell",
                "price": 30000.0,
                "amount": 0.05,
                "status": "opened",
            },
        ]
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
        )

        async with client:
            orders = await client.get_orders(trading_pair=trading_pair)

            # Ордера теперь валидны — недостающие поля заполняются значениями по умолчанию
            assert len(orders) == 2


# ==================== ByBitExchangeClient create_market_order Tests ====================


class TestByBitExchangeClientCreateMarketOrder:
    """Тесты создания рыночного ордера."""

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_create_market_order_buy(
        self,
        mock_bybit_class,
        mock_ccxt_exchange,
        trading_pair,
        sample_order_data,
        domain_exchange,
    ):
        """Тест создания рыночного ордера на покупку."""
        mock_ccxt_exchange.create_market_order.return_value = {"id": "order_123"}
        mock_ccxt_exchange.fetch_open_order.return_value = sample_order_data
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
        )

        async with client:
            order = await client.create_market_order(
                trading_pair=trading_pair,
                side=OrderSide.BUY,
                amount=Decimal("0.1"),
                price=Decimal("29000.0"),
            )

            assert isinstance(order, ExchangeClientOrder)
            assert order.side == OrderSide.BUY
            assert order.type == OrderType.MARKET
            mock_ccxt_exchange.create_market_order.assert_called_once_with(
                symbol=trading_pair.symbol,
                side=OrderSide.BUY,
                amount=Decimal("0.1"),
                params={},
            )

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_create_market_order_sell(
        self,
        mock_bybit_class,
        mock_ccxt_exchange,
        trading_pair,
        sample_order_data,
        domain_exchange,
    ):
        """Тест создания рыночного ордера на продажу."""
        mock_ccxt_exchange.create_market_order.return_value = {"id": "order_456"}
        sample_order_data["side"] = "sell"
        mock_ccxt_exchange.fetch_open_order.return_value = sample_order_data
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
        )

        async with client:
            order = await client.create_market_order(
                trading_pair=trading_pair,
                side=OrderSide.SELL,
                amount=Decimal("0.05"),
                price=Decimal("29000.0"),
            )

            assert order.side == OrderSide.SELL

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_create_market_order_with_params(
        self,
        mock_bybit_class,
        mock_ccxt_exchange,
        trading_pair,
        sample_order_data,
        domain_exchange,
    ):
        """Тест создания ордера с дополнительными параметрами."""
        mock_ccxt_exchange.create_market_order.return_value = {"id": "order_123"}
        mock_ccxt_exchange.fetch_open_order.return_value = sample_order_data
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
        )

        async with client:
            custom_params = {"reduceOnly": True}
            await client.create_market_order(
                trading_pair=trading_pair,
                side=OrderSide.BUY,
                amount=Decimal("0.1"),
                price=Decimal("29000.0"),
                params=custom_params,
            )

            call_args = mock_ccxt_exchange.create_market_order.call_args
            assert call_args[1]["params"] == custom_params


# ==================== ByBitExchangeClient get_open_orders Tests ====================


class TestByBitExchangeClientGetOpenOrders:
    """Тесты получения открытых ордеров."""

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_get_open_orders_success(
        self, mock_bybit_class, mock_ccxt_exchange, trading_pair, domain_exchange
    ):
        """Тест успешного получения открытых ордеров."""
        mock_ccxt_exchange.fetch_open_orders.return_value = [
            {"id": "order_1"},
            {"id": "order_2"},
        ]
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
        )

        async with client:
            orders = await client.get_open_orders(trading_pair=trading_pair)

            assert len(orders) == 2
            mock_ccxt_exchange.fetch_open_orders.assert_called_once_with(
                trading_pair.symbol
            )

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_get_open_orders_no_symbol(
        self, mock_bybit_class, mock_ccxt_exchange, domain_exchange
    ):
        """Тест получения всех открытых ордеров без указания пары."""
        mock_ccxt_exchange.fetch_open_orders.return_value = []
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
        )

        async with client:
            await client.get_open_orders(trading_pair=None)

            mock_ccxt_exchange.fetch_open_orders.assert_called_once_with(None)


# ==================== ByBitExchangeClient cancel_all_orders Tests ====================


class TestByBitExchangeClientCancelAllOrders:
    """Тесты отмены всех ордеров."""

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_cancel_all_orders(
        self, mock_bybit_class, mock_ccxt_exchange, trading_pair, domain_exchange
    ):
        """Тест отмены всех ордеров."""
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
        )

        async with client:
            await client.cancel_all_orders(trading_pair=trading_pair)

            mock_ccxt_exchange.cancel_all_orders.assert_called_once_with(
                trading_pair.symbol
            )


# ==================== Error Handling Tests ====================


class TestByBitExchangeClientErrorHandling:
    """Тесты обработки ошибок."""

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_authentication_error(
        self, mock_bybit_class, mock_ccxt_exchange, domain_exchange
    ):
        """Тест обработки ошибки аутентификации."""
        mock_ccxt_exchange.fetch_balance.side_effect = AuthenticationError(
            "Invalid API key"
        )
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="invalid_key",
            api_secret="invalid_secret",
        )

        async with client:
            with pytest.raises(AuthenticationError):
                await client.get_balances()

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_network_error(
        self, mock_bybit_class, mock_ccxt_exchange, trading_pair, domain_exchange
    ):
        """Тест обработки сетевой ошибки."""
        mock_ccxt_exchange.fetch_ohlcv.side_effect = NetworkError("Network error")
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
        )

        async with client:
            with pytest.raises(NetworkError):
                await client.fetch_candles(
                    trading_pair=trading_pair,
                    timeframe=Timeframe.ONE_HOUR,
                    since=None,
                    limit=100,
                )

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_rate_limit_error(
        self, mock_bybit_class, mock_ccxt_exchange, domain_exchange
    ):
        """Тест обработки ошибки превышения лимита запросов."""
        mock_ccxt_exchange.fetch_balance.side_effect = RateLimitExceeded(
            "Rate limit exceeded"
        )
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
        )

        async with client:
            with pytest.raises(RateLimitExceeded):
                await client.get_balances()


# ==================== OrderSide, OrderStatus, OrderType Enums Tests ====================


class TestEnums:
    """Тесты для enum типов."""

    def test_order_side_values(self):
        """Тест значений OrderSide."""
        assert OrderSide.BUY.value == "buy"
        assert OrderSide.SELL.value == "sell"

    def test_order_status_values(self):
        """Тест значений OrderStatus."""
        assert OrderStatus.OPENED.value == "opened"
        assert OrderStatus.CLOSED.value == "closed"
        assert OrderStatus.CANCELED.value == "canceled"

    def test_order_type_values(self):
        """Тест значений OrderType."""
        assert OrderType.MARKET.value == "market"
        assert OrderType.LIMIT.value == "limit"


# ==================== Edge Cases Tests ====================


class TestEdgeCases:
    """Тесты граничных случаев."""

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_very_large_candle_limit(
        self, mock_bybit_class, mock_ccxt_exchange, trading_pair, domain_exchange
    ):
        """Тест запроса очень большого количества свечей."""
        mock_ccxt_exchange.fetch_ohlcv.return_value = []
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
        )

        async with client:
            candles = await client.fetch_candles(
                trading_pair=trading_pair,
                timeframe=Timeframe.ONE_HOUR,
                since=None,
                limit=10000,  # Очень большой лимит
            )

            assert len(candles) == 0
            call_args = mock_ccxt_exchange.fetch_ohlcv.call_args
            assert call_args[1]["limit"] == 10000

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_zero_amount_order(
        self, mock_bybit_class, mock_ccxt_exchange, trading_pair, domain_exchange
    ):
        """Тест создания ордера с нулевым amount."""
        mock_ccxt_exchange.create_market_order.side_effect = ExchangeError(
            "Invalid amount"
        )
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
        )

        async with client:
            with pytest.raises(ExchangeError):
                await client.create_market_order(
                    trading_pair=trading_pair,
                    side=OrderSide.BUY,
                    amount=Decimal("0"),
                    price=Decimal("29000.0"),
                )

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_negative_amount_order(
        self, mock_bybit_class, mock_ccxt_exchange, trading_pair, domain_exchange
    ):
        """Тест создания ордера с отрицательным amount."""
        mock_ccxt_exchange.create_market_order.side_effect = ExchangeError(
            "Invalid amount"
        )
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
        )

        async with client:
            with pytest.raises(ExchangeError):
                await client.create_market_order(
                    trading_pair=trading_pair,
                    side=OrderSide.BUY,
                    amount=Decimal("-0.1"),
                    price=Decimal("29000.0"),
                )

    @pytest.mark.asyncio
    @patch("exchange_clients.domain.exchange_clients.bybit.ccxt.bybit")
    async def test_balance_with_very_large_numbers(
        self, mock_bybit_class, mock_ccxt_exchange, domain_exchange
    ):
        """Тест баланса с очень большими числами."""
        mock_ccxt_exchange.fetch_balance.return_value = {
            "BTC": {
                "free": 999999999.12345678,
                "used": 123456789.87654321,
                "total": 1123456789.0,
                "debt": 0.0,
            },
        }
        mock_bybit_class.return_value = mock_ccxt_exchange

        client = ByBitExchangeClient(
            exchange=domain_exchange,
            api_key="test_key",
            api_secret="test_secret",
        )

        async with client:
            balances = await client.get_balances()

            assert len(balances) == 1
            # Проверяем с точностью учитывая возможное округление float
            assert abs(float(balances[0].free) - 999999999.12345678) < 0.0001
