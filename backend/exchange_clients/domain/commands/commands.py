"""Команды для exchange worker."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from core.utils.cqrs import Command
from exchange_clients.domain.schemas import (
    ExchangeClientBalance,
    ExchangeClientOrder,
    OrderSide,
)
from exchanges.domain import TradingPair


class ExchangeClientCommand(Command[Any]):
    """Базовая команда exchange worker."""

    exchange_client_id: int


class FetchBalancesCommand(
    ExchangeClientCommand,
    Command[list[ExchangeClientBalance]],
):
    """Получение балансов."""


class GetOpenOrdersCommand(
    ExchangeClientCommand,
    Command[list[ExchangeClientOrder]],
):
    """Получение открытых ордеров."""

    trading_pair: TradingPair


class CreateMarketOrderCommand(
    ExchangeClientCommand,
    Command[ExchangeClientOrder],
):
    """Создание рыночного ордера."""

    trading_pair: TradingPair
    side: OrderSide
    amount: Decimal
    price: Decimal | None = None


class CancelAllOrdersCommand(ExchangeClientCommand, Command[None]):
    """Отмена всех ордеров."""

    trading_pair: TradingPair
