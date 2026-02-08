from datetime import datetime
from decimal import Decimal
from typing import Any

import ccxt.async_support as ccxt
from django.utils import timezone
from loguru import logger

from exchanges.domain import Candle, Timeframe, TradingPair

from .base import AbstractExchangeClient
from .proxies import ExchangeClientProxy
from .schemas import (
    ExchangeClientBalance,
    ExchangeClientOrder,
    OrderSide,
    OrderStatus,
    OrderType,
)


class ByBitExchangeClient(AbstractExchangeClient):
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        demo: bool = True,
        proxy: ExchangeClientProxy | None = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.exchange = ccxt.bybit(
            {
                "apiKey": self.api_key,
                "secret": self.api_secret,
                "enableRateLimit": True,
                "options": {
                    "defaultType": "future",
                },
            }
        )
        self.exchange.timeout = 10000  # 10 cекунд

        if demo:
            self.exchange.enable_demo_trading(True)

        if proxy:
            pass
            # connector = ProxyConnector.from_url(proxy.as_url())
            # session = aiohttp.ClientSession(connector=connector)
            # self.exchange.session = session

        # self.semaphore = asyncio.Semaphore(10)

    async def __aenter__(self) -> "ByBitExchangeClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self):
        await self.exchange.close()

    async def fetch_candles(
        self,
        trading_pair: TradingPair,
        timeframe: Timeframe = Timeframe.ONE_MINUTE,
        since: datetime | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[Candle]:
        if params is None:
            params = {}
        if since is not None:
            since = int(since.timestamp() * 1000)

        raw_ohlcv = await self.exchange.fetch_ohlcv(
            trading_pair.symbol,
            timeframe.value,
            limit=limit,
            since=since,
            params=params,
        )
        return [
            Candle(
                dt_unix=item[0],
                open=item[1],
                high=item[2],
                low=item[3],
                close=item[4],
                volume=item[5],
            )
            for item in raw_ohlcv
        ]

    async def get_balances(
        self, params: dict | None = None
    ) -> list[ExchangeClientBalance]:
        if params is None:
            params = {}
        balances_dict = await self.exchange.fetch_balance(params=params)
        return [
            ExchangeClientBalance(
                currency=currency,
                free=values["free"],
                total=values["total"],
                debt=values["debt"],
                used=values["used"],
            )
            for currency, values in balances_dict.items()
            if isinstance(values, dict)
            and all(
                key in values and values[key] is not None
                for key in ("free", "total", "debt", "used")
            )
        ]

    async def get_orders(
        self,
        trading_pair: TradingPair,
        since: int | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[ExchangeClientOrder]:
        if params is None:
            params = {}
        try:
            orders = await self.exchange.fetch_orders(
                symbol=trading_pair.symbol,
                since=since,
                limit=limit,
                params=params,
            )
        except Exception as e:
            logger.error(f"Ошибка при получении ордеров: {e}")
            return []

        result: list[ExchangeClientOrder] = []
        for order in orders:
            try:
                order_dto = ExchangeClientOrder(
                    timestamp=order["timestamp"],
                    side=order["side"],
                    price=order["price"],
                    amount=order["amount"],
                    status=order["status"],
                )
                result.append(order_dto)
            except Exception as e:
                logger.warning(f"Ошибка при валидации ордера {order}: {e}")
        return result

    async def create_market_order(
        self,
        trading_pair: TradingPair,
        side: OrderSide,
        amount: Decimal,
        params: dict | None = None,
    ) -> ExchangeClientOrder:
        if params is None:
            params = {}

        order_dict_id: dict = await self.exchange.create_market_order(
            symbol=trading_pair.symbol,
            side=side,
            amount=amount,
            params=params,
        )

        order_id = order_dict_id.get("id")
        order_dict = await self.exchange.fetch_open_order(order_id, trading_pair.symbol)

        return ExchangeClientOrder(
            trading_pair=trading_pair,
            side=side,
            type=OrderType.MARKET,
            amount=Decimal(str(order_dict["amount"])),
            price=Decimal(str(order_dict["average"])),
            status=OrderStatus(order_dict["status"]),
            timestamp=timezone.make_aware(
                datetime.fromtimestamp(order_dict["timestamp"] / 1000)
            ),
            cost=Decimal(str(order_dict["cost"])),
            exchange_order_id=order_dict["id"],
            fee=Decimal(str(order_dict["fee"]["cost"])),
        )

    async def get_open_orders(
        self, trading_pair: TradingPair | None = None
    ) -> list[dict[str, Any]]:
        symbol = trading_pair.symbol if trading_pair else None
        return await self.exchange.fetch_open_orders(symbol)

    async def cancel_all_orders(self, trading_pair: TradingPair) -> None:
        await self.exchange.cancel_all_orders(trading_pair.symbol)


class BinanceExchangeClient(AbstractExchangeClient):
    """Клиент для Binance Futures."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        demo: bool = True,
        proxy: ExchangeClientProxy | None = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.exchange = ccxt.binance(
            {
                "apiKey": self.api_key,
                "secret": self.api_secret,
                "enableRateLimit": True,
                "options": {
                    "defaultType": "future",
                },
            }
        )
        self.exchange.timeout = 10000

        if demo:
            self.exchange.set_sandbox_mode(True)

        if proxy:
            pass

    async def __aenter__(self) -> "BinanceExchangeClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self):
        await self.exchange.close()

    async def fetch_candles(
        self,
        trading_pair: TradingPair,
        timeframe: Timeframe = Timeframe.ONE_MINUTE,
        since: datetime | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[Candle]:
        if params is None:
            params = {}
        if isinstance(since, datetime):
            since = int(since.timestamp() * 1000)

        raw_ohlcv = await self.exchange.fetch_ohlcv(
            trading_pair.symbol,
            timeframe.value,
            limit=limit,
            since=since,
            params=params,
        )
        return [
            Candle(
                dt_unix=item[0],
                open=item[1],
                high=item[2],
                low=item[3],
                close=item[4],
                volume=item[5],
            )
            for item in raw_ohlcv
        ]

    async def get_balances(
        self, params: dict | None = None
    ) -> list[ExchangeClientBalance]:
        if params is None:
            params = {}
        balances_dict = await self.exchange.fetch_balance(params=params)
        return [
            ExchangeClientBalance(
                currency=currency,
                free=values["free"],
                total=values["total"],
                debt=values.get("debt", Decimal(0)),
                used=values["used"],
            )
            for currency, values in balances_dict.items()
            if isinstance(values, dict)
            and all(
                key in values and values[key] is not None
                for key in ("free", "total", "used")
            )
        ]

    async def get_orders(
        self,
        trading_pair: TradingPair,
        since: int | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[ExchangeClientOrder]:
        if params is None:
            params = {}
        try:
            orders = await self.exchange.fetch_orders(
                symbol=trading_pair.symbol,
                since=since,
                limit=limit,
                params=params,
            )
        except Exception as e:
            logger.error(f"Ошибка при получении ордеров: {e}")
            return []

        result: list[ExchangeClientOrder] = []
        for order in orders:
            try:
                order_dto = ExchangeClientOrder(
                    timestamp=order["timestamp"],
                    side=order["side"],
                    price=order["price"],
                    amount=order["amount"],
                    status=order["status"],
                )
                result.append(order_dto)
            except Exception as e:
                logger.warning(f"Ошибка при валидации ордера {order}: {e}")
        return result

    async def create_market_order(
        self,
        trading_pair: TradingPair,
        side: OrderSide,
        amount: Decimal,
        params: dict | None = None,
    ) -> ExchangeClientOrder:
        if params is None:
            params = {}

        order_dict_id: dict = await self.exchange.create_market_order(
            symbol=trading_pair.symbol,
            side=side,
            amount=amount,
            params=params,
        )

        order_id = order_dict_id.get("id")
        order_dict = await self.exchange.fetch_order(order_id, trading_pair.symbol)

        return ExchangeClientOrder(
            trading_pair=trading_pair,
            side=side,
            type=OrderType.MARKET,
            amount=Decimal(str(order_dict["amount"])),
            price=Decimal(str(order_dict["average"])),
            status=OrderStatus(order_dict["status"]),
            timestamp=timezone.make_aware(
                datetime.fromtimestamp(order_dict["timestamp"] / 1000)
            ),
            cost=Decimal(str(order_dict["cost"])),
            exchange_order_id=order_dict["id"],
            fee=Decimal(str(order_dict["fee"]["cost"]))
            if order_dict.get("fee")
            else Decimal(0),
        )

    async def get_open_orders(
        self, trading_pair: TradingPair | None = None
    ) -> list[dict[str, Any]]:
        symbol = trading_pair.symbol if trading_pair else None
        return await self.exchange.fetch_open_orders(symbol)

    async def cancel_all_orders(self, trading_pair: TradingPair) -> None:
        await self.exchange.cancel_all_orders(trading_pair.symbol)


class OKXExchangeClient(AbstractExchangeClient):
    """Клиент для OKX (ранее OKEx)."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        password: str = "",
        demo: bool = True,
        proxy: ExchangeClientProxy | None = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.password = password
        self.exchange = ccxt.okx(
            {
                "apiKey": self.api_key,
                "secret": self.api_secret,
                "password": self.password,
                "enableRateLimit": True,
                "options": {
                    "defaultType": "swap",
                },
            }
        )
        self.exchange.timeout = 10000

        if demo:
            self.exchange.set_sandbox_mode(True)

        if proxy:
            pass

    async def __aenter__(self) -> "OKXExchangeClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self):
        await self.exchange.close()

    async def fetch_candles(
        self,
        trading_pair: TradingPair,
        timeframe: Timeframe = Timeframe.ONE_MINUTE,
        since: datetime | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[Candle]:
        if params is None:
            params = {}
        if isinstance(since, datetime):
            since = int(since.timestamp() * 1000)

        raw_ohlcv = await self.exchange.fetch_ohlcv(
            trading_pair.symbol,
            timeframe.value,
            limit=limit,
            since=since,
            params=params,
        )
        return [
            Candle(
                dt_unix=item[0],
                open=item[1],
                high=item[2],
                low=item[3],
                close=item[4],
                volume=item[5],
            )
            for item in raw_ohlcv
        ]

    async def get_balances(
        self, params: dict | None = None
    ) -> list[ExchangeClientBalance]:
        if params is None:
            params = {}
        balances_dict = await self.exchange.fetch_balance(params=params)
        return [
            ExchangeClientBalance(
                currency=currency,
                free=values["free"],
                total=values["total"],
                debt=values.get("debt", Decimal(0)),
                used=values["used"],
            )
            for currency, values in balances_dict.items()
            if isinstance(values, dict)
            and all(
                key in values and values[key] is not None
                for key in ("free", "total", "used")
            )
        ]

    async def get_orders(
        self,
        trading_pair: TradingPair,
        since: int | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[ExchangeClientOrder]:
        if params is None:
            params = {}
        try:
            orders = await self.exchange.fetch_orders(
                symbol=trading_pair.symbol,
                since=since,
                limit=limit,
                params=params,
            )
        except Exception as e:
            logger.error(f"Ошибка при получении ордеров: {e}")
            return []

        result: list[ExchangeClientOrder] = []
        for order in orders:
            try:
                order_dto = ExchangeClientOrder(
                    timestamp=order["timestamp"],
                    side=order["side"],
                    price=order["price"],
                    amount=order["amount"],
                    status=order["status"],
                )
                result.append(order_dto)
            except Exception as e:
                logger.warning(f"Ошибка при валидации ордера {order}: {e}")
        return result

    async def create_market_order(
        self,
        trading_pair: TradingPair,
        side: OrderSide,
        amount: Decimal,
        params: dict | None = None,
    ) -> ExchangeClientOrder:
        if params is None:
            params = {}

        order_dict_id: dict = await self.exchange.create_market_order(
            symbol=trading_pair.symbol,
            side=side,
            amount=amount,
            params=params,
        )

        order_id = order_dict_id.get("id")
        order_dict = await self.exchange.fetch_order(order_id, trading_pair.symbol)

        return ExchangeClientOrder(
            trading_pair=trading_pair,
            side=side,
            type=OrderType.MARKET,
            amount=Decimal(str(order_dict["amount"])),
            price=Decimal(str(order_dict["average"])),
            status=OrderStatus(order_dict["status"]),
            timestamp=timezone.make_aware(
                datetime.fromtimestamp(order_dict["timestamp"] / 1000)
            ),
            cost=Decimal(str(order_dict["cost"])),
            exchange_order_id=order_dict["id"],
            fee=Decimal(str(order_dict["fee"]["cost"]))
            if order_dict.get("fee")
            else Decimal(0),
        )

    async def get_open_orders(
        self, trading_pair: TradingPair | None = None
    ) -> list[dict[str, Any]]:
        symbol = trading_pair.symbol if trading_pair else None
        return await self.exchange.fetch_open_orders(symbol)

    async def cancel_all_orders(self, trading_pair: TradingPair) -> None:
        await self.exchange.cancel_all_orders(trading_pair.symbol)


class KrakenExchangeClient(AbstractExchangeClient):
    """Клиент для Kraken Futures.

    Demo-режим (sandbox) отключён: демо-сервер Kraken Futures не содержит
    исторических данных по свечам, поэтому sandbox всегда выключен.
    Для публичных данных (OHLCV) API-ключи не требуются.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        demo: bool = True,
        proxy: ExchangeClientProxy | None = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.exchange = ccxt.krakenfutures(
            {
                "apiKey": self.api_key,
                "secret": self.api_secret,
                "enableRateLimit": True,
            }
        )
        self.exchange.timeout = 10000

        if proxy:
            pass

    async def __aenter__(self) -> "KrakenExchangeClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self):
        await self.exchange.close()

    async def fetch_candles(
        self,
        trading_pair: TradingPair,
        timeframe: Timeframe = Timeframe.ONE_MINUTE,
        since: datetime | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[Candle]:
        if params is None:
            params = {}
        if isinstance(since, datetime):
            since = int(since.timestamp() * 1000)

        raw_ohlcv = await self.exchange.fetch_ohlcv(
            trading_pair.symbol,
            timeframe.value,
            limit=limit,
            since=since,
            params=params,
        )
        return [
            Candle(
                dt_unix=item[0],
                open=item[1],
                high=item[2],
                low=item[3],
                close=item[4],
                volume=item[5],
            )
            for item in raw_ohlcv
        ]

    async def get_balances(
        self, params: dict | None = None
    ) -> list[ExchangeClientBalance]:
        if params is None:
            params = {}
        balances_dict = await self.exchange.fetch_balance(params=params)
        return [
            ExchangeClientBalance(
                currency=currency,
                free=values["free"],
                total=values["total"],
                debt=values.get("debt", Decimal(0)),
                used=values["used"],
            )
            for currency, values in balances_dict.items()
            if isinstance(values, dict)
            and all(
                key in values and values[key] is not None
                for key in ("free", "total", "used")
            )
        ]

    async def get_orders(
        self,
        trading_pair: TradingPair,
        since: int | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[ExchangeClientOrder]:
        if params is None:
            params = {}
        try:
            orders = await self.exchange.fetch_orders(
                symbol=trading_pair.symbol,
                since=since,
                limit=limit,
                params=params,
            )
        except Exception as e:
            logger.error(f"Ошибка при получении ордеров: {e}")
            return []

        result: list[ExchangeClientOrder] = []
        for order in orders:
            try:
                order_dto = ExchangeClientOrder(
                    timestamp=order["timestamp"],
                    side=order["side"],
                    price=order["price"],
                    amount=order["amount"],
                    status=order["status"],
                )
                result.append(order_dto)
            except Exception as e:
                logger.warning(f"Ошибка при валидации ордера {order}: {e}")
        return result

    async def create_market_order(
        self,
        trading_pair: TradingPair,
        side: OrderSide,
        amount: Decimal,
        params: dict | None = None,
    ) -> ExchangeClientOrder:
        if params is None:
            params = {}

        order_dict_id: dict = await self.exchange.create_market_order(
            symbol=trading_pair.symbol,
            side=side,
            amount=amount,
            params=params,
        )

        order_id = order_dict_id.get("id")
        order_dict = await self.exchange.fetch_order(order_id, trading_pair.symbol)

        return ExchangeClientOrder(
            trading_pair=trading_pair,
            side=side,
            type=OrderType.MARKET,
            amount=Decimal(str(order_dict["amount"])),
            price=Decimal(str(order_dict["average"])),
            status=OrderStatus(order_dict["status"]),
            timestamp=timezone.make_aware(
                datetime.fromtimestamp(order_dict["timestamp"] / 1000)
            ),
            cost=Decimal(str(order_dict["cost"])),
            exchange_order_id=order_dict["id"],
            fee=Decimal(str(order_dict["fee"]["cost"]))
            if order_dict.get("fee")
            else Decimal(0),
        )

    async def get_open_orders(
        self, trading_pair: TradingPair | None = None
    ) -> list[dict[str, Any]]:
        symbol = trading_pair.symbol if trading_pair else None
        return await self.exchange.fetch_open_orders(symbol)

    async def cancel_all_orders(self, trading_pair: TradingPair) -> None:
        await self.exchange.cancel_all_orders(trading_pair.symbol)


class BitgetExchangeClient(AbstractExchangeClient):
    """Клиент для Bitget."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        password: str = "",
        demo: bool = True,
        proxy: ExchangeClientProxy | None = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.password = password
        self.exchange = ccxt.bitget(
            {
                "apiKey": self.api_key,
                "secret": self.api_secret,
                "password": self.password,
                "enableRateLimit": True,
                "options": {
                    "defaultType": "swap",
                },
            }
        )
        self.exchange.timeout = 10000

        if demo:
            self.exchange.set_sandbox_mode(True)

        if proxy:
            pass

    async def __aenter__(self) -> "BitgetExchangeClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self):
        await self.exchange.close()

    async def fetch_candles(
        self,
        trading_pair: TradingPair,
        timeframe: Timeframe = Timeframe.ONE_MINUTE,
        since: datetime | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[Candle]:
        if params is None:
            params = {}
        if isinstance(since, datetime):
            since = int(since.timestamp() * 1000)

        raw_ohlcv = await self.exchange.fetch_ohlcv(
            trading_pair.symbol,
            timeframe.value,
            limit=limit,
            since=since,
            params=params,
        )
        return [
            Candle(
                dt_unix=item[0],
                open=item[1],
                high=item[2],
                low=item[3],
                close=item[4],
                volume=item[5],
            )
            for item in raw_ohlcv
        ]

    async def get_balances(
        self, params: dict | None = None
    ) -> list[ExchangeClientBalance]:
        if params is None:
            params = {}
        balances_dict = await self.exchange.fetch_balance(params=params)
        return [
            ExchangeClientBalance(
                currency=currency,
                free=values["free"],
                total=values["total"],
                debt=values.get("debt", Decimal(0)),
                used=values["used"],
            )
            for currency, values in balances_dict.items()
            if isinstance(values, dict)
            and all(
                key in values and values[key] is not None
                for key in ("free", "total", "used")
            )
        ]

    async def get_orders(
        self,
        trading_pair: TradingPair,
        since: int | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[ExchangeClientOrder]:
        if params is None:
            params = {}
        try:
            orders = await self.exchange.fetch_orders(
                symbol=trading_pair.symbol,
                since=since,
                limit=limit,
                params=params,
            )
        except Exception as e:
            logger.error(f"Ошибка при получении ордеров: {e}")
            return []

        result: list[ExchangeClientOrder] = []
        for order in orders:
            try:
                order_dto = ExchangeClientOrder(
                    timestamp=order["timestamp"],
                    side=order["side"],
                    price=order["price"],
                    amount=order["amount"],
                    status=order["status"],
                )
                result.append(order_dto)
            except Exception as e:
                logger.warning(f"Ошибка при валидации ордера {order}: {e}")
        return result

    async def create_market_order(
        self,
        trading_pair: TradingPair,
        side: OrderSide,
        amount: Decimal,
        params: dict | None = None,
    ) -> ExchangeClientOrder:
        if params is None:
            params = {}

        order_dict_id: dict = await self.exchange.create_market_order(
            symbol=trading_pair.symbol,
            side=side,
            amount=amount,
            params=params,
        )

        order_id = order_dict_id.get("id")
        order_dict = await self.exchange.fetch_order(order_id, trading_pair.symbol)

        return ExchangeClientOrder(
            trading_pair=trading_pair,
            side=side,
            type=OrderType.MARKET,
            amount=Decimal(str(order_dict["amount"])),
            price=Decimal(str(order_dict["average"])),
            status=OrderStatus(order_dict["status"]),
            timestamp=timezone.make_aware(
                datetime.fromtimestamp(order_dict["timestamp"] / 1000)
            ),
            cost=Decimal(str(order_dict["cost"])),
            exchange_order_id=order_dict["id"],
            fee=Decimal(str(order_dict["fee"]["cost"]))
            if order_dict.get("fee")
            else Decimal(0),
        )

    async def get_open_orders(
        self, trading_pair: TradingPair | None = None
    ) -> list[dict[str, Any]]:
        symbol = trading_pair.symbol if trading_pair else None
        return await self.exchange.fetch_open_orders(symbol)

    async def cancel_all_orders(self, trading_pair: TradingPair) -> None:
        await self.exchange.cancel_all_orders(trading_pair.symbol)


class CoinbaseExchangeClient(AbstractExchangeClient):
    """Клиент для Coinbase."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        demo: bool = True,
        proxy: ExchangeClientProxy | None = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.exchange = ccxt.coinbase(
            {
                "apiKey": self.api_key,
                "secret": self.api_secret,
                "enableRateLimit": True,
            }
        )
        self.exchange.timeout = 10000
        if demo:
            self.exchange.set_sandbox_mode(True)

    async def __aenter__(self) -> "CoinbaseExchangeClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self):
        await self.exchange.close()

    async def fetch_candles(
        self,
        trading_pair: TradingPair,
        timeframe: Timeframe = Timeframe.ONE_MINUTE,
        since: datetime | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[Candle]:
        if params is None:
            params = {}
        if isinstance(since, datetime):
            since = int(since.timestamp() * 1000)
        raw_ohlcv = await self.exchange.fetch_ohlcv(
            trading_pair.symbol,
            timeframe.value,
            limit=limit,
            since=since,
            params=params,
        )
        return [
            Candle(
                dt_unix=item[0],
                open=item[1],
                high=item[2],
                low=item[3],
                close=item[4],
                volume=item[5],
            )
            for item in raw_ohlcv
        ]

    async def get_balances(
        self, params: dict | None = None
    ) -> list[ExchangeClientBalance]:
        return []

    async def get_orders(
        self,
        trading_pair: TradingPair,
        since: int | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[ExchangeClientOrder]:
        return []

    async def create_market_order(
        self,
        trading_pair: TradingPair,
        side: OrderSide,
        amount: Decimal,
        params: dict | None = None,
    ) -> ExchangeClientOrder:
        raise NotImplementedError()

    async def get_open_orders(
        self, trading_pair: TradingPair | None = None
    ) -> list[dict[str, Any]]:
        return []

    async def cancel_all_orders(self, trading_pair: TradingPair) -> None:
        pass


class KuCoinExchangeClient(AbstractExchangeClient):
    """Клиент для KuCoin Futures."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        password: str = "",
        demo: bool = True,
        proxy: ExchangeClientProxy | None = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.password = password
        self.exchange = ccxt.kucoinfutures(
            {
                "apiKey": self.api_key,
                "secret": self.api_secret,
                "password": self.password,
                "enableRateLimit": True,
            }
        )
        self.exchange.timeout = 10000
        if demo:
            self.exchange.set_sandbox_mode(True)

    async def __aenter__(self) -> "KuCoinExchangeClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self):
        await self.exchange.close()

    async def fetch_candles(
        self,
        trading_pair: TradingPair,
        timeframe: Timeframe = Timeframe.ONE_MINUTE,
        since: datetime | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[Candle]:
        if params is None:
            params = {}
        if isinstance(since, datetime):
            since = int(since.timestamp() * 1000)
        raw_ohlcv = await self.exchange.fetch_ohlcv(
            trading_pair.symbol,
            timeframe.value,
            limit=limit,
            since=since,
            params=params,
        )
        return [
            Candle(
                dt_unix=item[0],
                open=item[1],
                high=item[2],
                low=item[3],
                close=item[4],
                volume=item[5],
            )
            for item in raw_ohlcv
        ]

    async def get_balances(
        self, params: dict | None = None
    ) -> list[ExchangeClientBalance]:
        return []

    async def get_orders(
        self,
        trading_pair: TradingPair,
        since: int | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[ExchangeClientOrder]:
        return []

    async def create_market_order(
        self,
        trading_pair: TradingPair,
        side: OrderSide,
        amount: Decimal,
        params: dict | None = None,
    ) -> ExchangeClientOrder:
        raise NotImplementedError()

    async def get_open_orders(
        self, trading_pair: TradingPair | None = None
    ) -> list[dict[str, Any]]:
        return []

    async def cancel_all_orders(self, trading_pair: TradingPair) -> None:
        pass


class GateIOExchangeClient(AbstractExchangeClient):
    """Клиент для Gate.io."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        demo: bool = True,
        proxy: ExchangeClientProxy | None = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.exchange = ccxt.gateio(
            {
                "apiKey": self.api_key,
                "secret": self.api_secret,
                "enableRateLimit": True,
                "options": {"defaultType": "swap"},
            }
        )
        self.exchange.timeout = 10000
        if demo:
            self.exchange.set_sandbox_mode(True)

    async def __aenter__(self) -> "GateIOExchangeClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self):
        await self.exchange.close()

    async def fetch_candles(
        self,
        trading_pair: TradingPair,
        timeframe: Timeframe = Timeframe.ONE_MINUTE,
        since: datetime | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[Candle]:
        if params is None:
            params = {}
        if isinstance(since, datetime):
            since = int(since.timestamp() * 1000)
        raw_ohlcv = await self.exchange.fetch_ohlcv(
            trading_pair.symbol,
            timeframe.value,
            limit=limit,
            since=since,
            params=params,
        )
        return [
            Candle(
                dt_unix=item[0],
                open=item[1],
                high=item[2],
                low=item[3],
                close=item[4],
                volume=item[5],
            )
            for item in raw_ohlcv
        ]

    async def get_balances(
        self, params: dict | None = None
    ) -> list[ExchangeClientBalance]:
        return []

    async def get_orders(
        self,
        trading_pair: TradingPair,
        since: int | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[ExchangeClientOrder]:
        return []

    async def create_market_order(
        self,
        trading_pair: TradingPair,
        side: OrderSide,
        amount: Decimal,
        params: dict | None = None,
    ) -> ExchangeClientOrder:
        raise NotImplementedError()

    async def get_open_orders(
        self, trading_pair: TradingPair | None = None
    ) -> list[dict[str, Any]]:
        return []

    async def cancel_all_orders(self, trading_pair: TradingPair) -> None:
        pass


class HTXExchangeClient(AbstractExchangeClient):
    """Клиент для HTX (Huobi)."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        demo: bool = True,
        proxy: ExchangeClientProxy | None = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.exchange = ccxt.htx(
            {
                "apiKey": self.api_key,
                "secret": self.api_secret,
                "enableRateLimit": True,
                "options": {"defaultType": "swap"},
            }
        )
        self.exchange.timeout = 10000
        if demo:
            self.exchange.set_sandbox_mode(True)

    async def __aenter__(self) -> "HTXExchangeClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self):
        await self.exchange.close()

    async def fetch_candles(
        self,
        trading_pair: TradingPair,
        timeframe: Timeframe = Timeframe.ONE_MINUTE,
        since: datetime | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[Candle]:
        if params is None:
            params = {}
        if isinstance(since, datetime):
            since = int(since.timestamp() * 1000)
        raw_ohlcv = await self.exchange.fetch_ohlcv(
            trading_pair.symbol,
            timeframe.value,
            limit=limit,
            since=since,
            params=params,
        )
        return [
            Candle(
                dt_unix=item[0],
                open=item[1],
                high=item[2],
                low=item[3],
                close=item[4],
                volume=item[5],
            )
            for item in raw_ohlcv
        ]

    async def get_balances(
        self, params: dict | None = None
    ) -> list[ExchangeClientBalance]:
        return []

    async def get_orders(
        self,
        trading_pair: TradingPair,
        since: int | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[ExchangeClientOrder]:
        return []

    async def create_market_order(
        self,
        trading_pair: TradingPair,
        side: OrderSide,
        amount: Decimal,
        params: dict | None = None,
    ) -> ExchangeClientOrder:
        raise NotImplementedError()

    async def get_open_orders(
        self, trading_pair: TradingPair | None = None
    ) -> list[dict[str, Any]]:
        return []

    async def cancel_all_orders(self, trading_pair: TradingPair) -> None:
        pass


class MEXCExchangeClient(AbstractExchangeClient):
    """Клиент для MEXC."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        demo: bool = True,
        proxy: ExchangeClientProxy | None = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.exchange = ccxt.mexc(
            {
                "apiKey": self.api_key,
                "secret": self.api_secret,
                "enableRateLimit": True,
                "options": {"defaultType": "swap"},
            }
        )
        self.exchange.timeout = 10000
        if demo:
            self.exchange.set_sandbox_mode(True)

    async def __aenter__(self) -> "MEXCExchangeClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self):
        await self.exchange.close()

    async def fetch_candles(
        self,
        trading_pair: TradingPair,
        timeframe: Timeframe = Timeframe.ONE_MINUTE,
        since: datetime | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[Candle]:
        if params is None:
            params = {}
        if isinstance(since, datetime):
            since = int(since.timestamp() * 1000)
        raw_ohlcv = await self.exchange.fetch_ohlcv(
            trading_pair.symbol,
            timeframe.value,
            limit=limit,
            since=since,
            params=params,
        )
        return [
            Candle(
                dt_unix=item[0],
                open=item[1],
                high=item[2],
                low=item[3],
                close=item[4],
                volume=item[5],
            )
            for item in raw_ohlcv
        ]

    async def get_balances(
        self, params: dict | None = None
    ) -> list[ExchangeClientBalance]:
        return []

    async def get_orders(
        self,
        trading_pair: TradingPair,
        since: int | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[ExchangeClientOrder]:
        return []

    async def create_market_order(
        self,
        trading_pair: TradingPair,
        side: OrderSide,
        amount: Decimal,
        params: dict | None = None,
    ) -> ExchangeClientOrder:
        raise NotImplementedError()

    async def get_open_orders(
        self, trading_pair: TradingPair | None = None
    ) -> list[dict[str, Any]]:
        return []

    async def cancel_all_orders(self, trading_pair: TradingPair) -> None:
        pass


class PhemexExchangeClient(AbstractExchangeClient):
    """Клиент для Phemex."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        demo: bool = True,
        proxy: ExchangeClientProxy | None = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.exchange = ccxt.phemex(
            {
                "apiKey": self.api_key,
                "secret": self.api_secret,
                "enableRateLimit": True,
                "options": {"defaultType": "swap"},
            }
        )
        self.exchange.timeout = 10000
        if demo:
            self.exchange.set_sandbox_mode(True)

    async def __aenter__(self) -> "PhemexExchangeClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self):
        await self.exchange.close()

    async def fetch_candles(
        self,
        trading_pair: TradingPair,
        timeframe: Timeframe = Timeframe.ONE_MINUTE,
        since: datetime | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[Candle]:
        if params is None:
            params = {}
        if isinstance(since, datetime):
            since = int(since.timestamp() * 1000)
        raw_ohlcv = await self.exchange.fetch_ohlcv(
            trading_pair.symbol,
            timeframe.value,
            limit=limit,
            since=since,
            params=params,
        )
        return [
            Candle(
                dt_unix=item[0],
                open=item[1],
                high=item[2],
                low=item[3],
                close=item[4],
                volume=item[5],
            )
            for item in raw_ohlcv
        ]

    async def get_balances(
        self, params: dict | None = None
    ) -> list[ExchangeClientBalance]:
        return []

    async def get_orders(
        self,
        trading_pair: TradingPair,
        since: int | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[ExchangeClientOrder]:
        return []

    async def create_market_order(
        self,
        trading_pair: TradingPair,
        side: OrderSide,
        amount: Decimal,
        params: dict | None = None,
    ) -> ExchangeClientOrder:
        raise NotImplementedError()

    async def get_open_orders(
        self, trading_pair: TradingPair | None = None
    ) -> list[dict[str, Any]]:
        return []

    async def cancel_all_orders(self, trading_pair: TradingPair) -> None:
        pass


class DeribitExchangeClient(AbstractExchangeClient):
    """Клиент для Deribit.

    Demo-режим (sandbox) отключён: демо-сервер Deribit не содержит
    исторических данных по свечам, поэтому sandbox всегда выключен.
    Для публичных данных (OHLCV) API-ключи не требуются.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        demo: bool = True,
        proxy: ExchangeClientProxy | None = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.exchange = ccxt.deribit(
            {"apiKey": self.api_key, "secret": self.api_secret, "enableRateLimit": True}
        )
        self.exchange.timeout = 10000

    async def __aenter__(self) -> "DeribitExchangeClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self):
        await self.exchange.close()

    async def fetch_candles(
        self,
        trading_pair: TradingPair,
        timeframe: Timeframe = Timeframe.ONE_MINUTE,
        since: datetime | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[Candle]:
        if params is None:
            params = {}
        if isinstance(since, datetime):
            since = int(since.timestamp() * 1000)
        raw_ohlcv = await self.exchange.fetch_ohlcv(
            trading_pair.symbol,
            timeframe.value,
            limit=limit,
            since=since,
            params=params,
        )
        return [
            Candle(
                dt_unix=item[0],
                open=item[1],
                high=item[2],
                low=item[3],
                close=item[4],
                volume=item[5],
            )
            for item in raw_ohlcv
        ]

    async def get_balances(
        self, params: dict | None = None
    ) -> list[ExchangeClientBalance]:
        return []

    async def get_orders(
        self,
        trading_pair: TradingPair,
        since: int | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[ExchangeClientOrder]:
        return []

    async def create_market_order(
        self,
        trading_pair: TradingPair,
        side: OrderSide,
        amount: Decimal,
        params: dict | None = None,
    ) -> ExchangeClientOrder:
        raise NotImplementedError()

    async def get_open_orders(
        self, trading_pair: TradingPair | None = None
    ) -> list[dict[str, Any]]:
        return []

    async def cancel_all_orders(self, trading_pair: TradingPair) -> None:
        pass


class BitMEXExchangeClient(AbstractExchangeClient):
    """Клиент для BitMEX."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        demo: bool = True,
        proxy: ExchangeClientProxy | None = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.exchange = ccxt.bitmex(
            {"apiKey": self.api_key, "secret": self.api_secret, "enableRateLimit": True}
        )
        self.exchange.timeout = 10000
        if demo:
            self.exchange.set_sandbox_mode(True)

    async def __aenter__(self) -> "BitMEXExchangeClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self):
        await self.exchange.close()

    async def fetch_candles(
        self,
        trading_pair: TradingPair,
        timeframe: Timeframe = Timeframe.ONE_MINUTE,
        since: datetime | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[Candle]:
        if params is None:
            params = {}
        if isinstance(since, datetime):
            since = int(since.timestamp() * 1000)
        raw_ohlcv = await self.exchange.fetch_ohlcv(
            trading_pair.symbol,
            timeframe.value,
            limit=limit,
            since=since,
            params=params,
        )
        return [
            Candle(
                dt_unix=item[0],
                open=item[1],
                high=item[2],
                low=item[3],
                close=item[4],
                volume=item[5],
            )
            for item in raw_ohlcv
        ]

    async def get_balances(
        self, params: dict | None = None
    ) -> list[ExchangeClientBalance]:
        return []

    async def get_orders(
        self,
        trading_pair: TradingPair,
        since: int | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[ExchangeClientOrder]:
        return []

    async def create_market_order(
        self,
        trading_pair: TradingPair,
        side: OrderSide,
        amount: Decimal,
        params: dict | None = None,
    ) -> ExchangeClientOrder:
        raise NotImplementedError()

    async def get_open_orders(
        self, trading_pair: TradingPair | None = None
    ) -> list[dict[str, Any]]:
        return []

    async def cancel_all_orders(self, trading_pair: TradingPair) -> None:
        pass


class BitfinexExchangeClient(AbstractExchangeClient):
    """Клиент для Bitfinex."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        demo: bool = True,
        proxy: ExchangeClientProxy | None = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.exchange = ccxt.bitfinex(
            {"apiKey": self.api_key, "secret": self.api_secret, "enableRateLimit": True}
        )
        self.exchange.timeout = 10000
        if demo:
            self.exchange.set_sandbox_mode(True)

    async def __aenter__(self) -> "BitfinexExchangeClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self):
        await self.exchange.close()

    async def fetch_candles(
        self,
        trading_pair: TradingPair,
        timeframe: Timeframe = Timeframe.ONE_MINUTE,
        since: datetime | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[Candle]:
        if params is None:
            params = {}
        if isinstance(since, datetime):
            since = int(since.timestamp() * 1000)
        raw_ohlcv = await self.exchange.fetch_ohlcv(
            trading_pair.symbol,
            timeframe.value,
            limit=limit,
            since=since,
            params=params,
        )
        return [
            Candle(
                dt_unix=item[0],
                open=item[1],
                high=item[2],
                low=item[3],
                close=item[4],
                volume=item[5],
            )
            for item in raw_ohlcv
        ]

    async def get_balances(
        self, params: dict | None = None
    ) -> list[ExchangeClientBalance]:
        return []

    async def get_orders(
        self,
        trading_pair: TradingPair,
        since: int | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[ExchangeClientOrder]:
        return []

    async def create_market_order(
        self,
        trading_pair: TradingPair,
        side: OrderSide,
        amount: Decimal,
        params: dict | None = None,
    ) -> ExchangeClientOrder:
        raise NotImplementedError()

    async def get_open_orders(
        self, trading_pair: TradingPair | None = None
    ) -> list[dict[str, Any]]:
        return []

    async def cancel_all_orders(self, trading_pair: TradingPair) -> None:
        pass
