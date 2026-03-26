"""Сообщения для exchange worker."""

from __future__ import annotations

from decimal import Decimal

from core.utils.cqrs import Message, Result
from exchange_clients.domain.schemas import (
    ExchangeClientBalance,
    ExchangeClientOrder,
    OrderSide,
)
from exchanges.domain import TradingPair


class ExchangeClientMessage(Message):
    """Базовое сообщение exchange worker."""

    exchange_client_id: int


class FetchBalancesResult(Result):
    """Результат получения балансов."""

    balances: list[ExchangeClientBalance]


class FetchBalancesMessage(ExchangeClientMessage):
    """Получение балансов."""


class GetOpenOrdersResult(Result):
    """Результат получения открытых ордеров."""

    orders: list[ExchangeClientOrder]


class GetOpenOrdersMessage(ExchangeClientMessage):
    """Получение открытых ордеров."""

    trading_pair: TradingPair


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
