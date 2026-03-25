"""Хендлеры команд для exchange worker."""

from typing import Any

from core.utils.cqrs import CommandHandler
from exchange_clients.domain.base import AbstractExchangeClient
from exchange_clients.domain.schemas import (
    ExchangeClientBalance,
    ExchangeClientOrder,
)

from .commands import (
    CancelAllOrdersCommand,
    CreateMarketOrderCommand,
    FetchBalancesCommand,
    GetOpenOrdersCommand,
)


class ExchangeClientCommandHandler(CommandHandler):
    """Базовый хендлер с exchange client в конструкторе."""

    def __init__(self, client: AbstractExchangeClient) -> None:
        self._client = client

    async def handle(self, command: Any) -> Any:
        raise NotImplementedError


@FetchBalancesCommand.handler
class FetchBalancesHandler(ExchangeClientCommandHandler):
    async def handle(
        self,
        command: FetchBalancesCommand,  # type: ignore[override]
    ) -> list[ExchangeClientBalance]:
        return await self._client.get_balances()


@GetOpenOrdersCommand.handler
class GetOpenOrdersHandler(ExchangeClientCommandHandler):
    async def handle(
        self,
        command: GetOpenOrdersCommand,  # type: ignore[override]
    ) -> Any:
        return await self._client.get_open_orders(
            trading_pair=command.trading_pair,
        )


@CreateMarketOrderCommand.handler
class CreateMarketOrderHandler(ExchangeClientCommandHandler):
    async def handle(
        self,
        command: CreateMarketOrderCommand,  # type: ignore[override]
    ) -> ExchangeClientOrder:
        return await self._client.create_market_order(
            trading_pair=command.trading_pair,
            side=command.side,
            amount=command.amount,
            price=command.price,
        )


@CancelAllOrdersCommand.handler
class CancelAllOrdersHandler(ExchangeClientCommandHandler):
    async def handle(
        self,
        command: CancelAllOrdersCommand,  # type: ignore[override]
    ) -> None:
        await self._client.cancel_all_orders(
            trading_pair=command.trading_pair,
        )
