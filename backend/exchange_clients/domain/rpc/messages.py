"""Сообщения для exchange worker."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from core.utils.rpc import Message, Result
from exchange_clients.domain.schemas import (
    ExchangeClientBalance,
    ExchangeClientOrder,
    MarginMode,
    OrderSide,
)
from exchanges.domain import Candle, Timeframe, TradingPair
from exchanges.domain.schemas import MarketType


class ExchangeClientMessage(Message):
    """Базовое сообщение exchange worker."""

    exchange_client_id: int


class FetchBalancesResult(Result):
    """Результат получения балансов."""

    balances: list[ExchangeClientBalance]


class FetchBalancesMessage(ExchangeClientMessage):
    """Получение балансов."""

    market_type: MarketType


class FetchTradingPairsResult(Result):
    """Результат получения торговых пар."""

    trading_pairs: list[TradingPair]


class FetchTradingPairsMessage(ExchangeClientMessage):
    """Получение торговых пар через аутентифицированный клиент."""

    market_type: MarketType


class CreateMarketOrderResult(Result):
    """Результат создания рыночного ордера."""

    order: ExchangeClientOrder


class CreateMarketOrderMessage(ExchangeClientMessage):
    """Создание рыночного ордера."""

    trading_pair: TradingPair
    side: OrderSide
    amount: Decimal
    price: Decimal


class FetchOrderResult(Result):
    """Результат получения ордера."""

    order: ExchangeClientOrder


class FetchOrderMessage(ExchangeClientMessage):
    """Получение ордера по ID для синхронизации."""

    exchange_order_id: str
    trading_pair: TradingPair


class CancelAllOrdersMessage(ExchangeClientMessage):
    """Отмена всех ордеров."""

    trading_pair: TradingPair


class FetchCandlesResult(Result):
    """Результат получения свечей."""

    candles: list[Candle]


class FetchCandlesMessage(ExchangeClientMessage):
    """Получение свечей с биржи."""

    trading_pair: TradingPair
    timeframe: Timeframe
    since: datetime | None = None
    limit: int | None = None


class SetMarginModeMessage(ExchangeClientMessage):
    """Установка режима маржи."""

    margin_mode: MarginMode
    trading_pair: TradingPair


class SetLeverageMessage(ExchangeClientMessage):
    """Установка кредитного плеча."""

    leverage: float
    trading_pair: TradingPair
