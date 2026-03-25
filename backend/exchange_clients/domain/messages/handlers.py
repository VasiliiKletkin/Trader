"""Хендлеры сообщений для exchange worker."""

from core.utils.cqrs import Handler, Registry
from exchange_clients.domain.base import AbstractExchangeClient

from .messages import (
    CancelAllOrdersMessage,
    CreateMarketOrderMessage,
    CreateMarketOrderResult,
    FetchBalancesMessage,
    FetchBalancesResult,
    GetOpenOrdersMessage,
    GetOpenOrdersResult,
)


class ExchangeClientHandler(Handler):
    """Базовый хендлер с exchange client в конструкторе."""

    def __init__(self, client: AbstractExchangeClient) -> None:
        self._client = client


@Registry.handler(FetchBalancesMessage, FetchBalancesResult)
class FetchBalancesHandler(ExchangeClientHandler):
    async def handle(self, message: FetchBalancesMessage) -> FetchBalancesResult:
        balances = await self._client.get_balances()
        return FetchBalancesResult(balances=balances)


@Registry.handler(GetOpenOrdersMessage, GetOpenOrdersResult)
class GetOpenOrdersHandler(ExchangeClientHandler):
    async def handle(self, message: GetOpenOrdersMessage) -> GetOpenOrdersResult:
        orders = await self._client.get_open_orders(
            trading_pair=message.trading_pair,
        )
        return GetOpenOrdersResult(orders=orders)


@Registry.handler(CreateMarketOrderMessage, CreateMarketOrderResult)
class CreateMarketOrderHandler(ExchangeClientHandler):
    async def handle(
        self,
        message: CreateMarketOrderMessage,
    ) -> CreateMarketOrderResult:
        order = await self._client.create_market_order(
            trading_pair=message.trading_pair,
            side=message.side,
            amount=message.amount,
            price=message.price,
        )
        return CreateMarketOrderResult(order=order)


@Registry.handler(CancelAllOrdersMessage)
class CancelAllOrdersHandler(ExchangeClientHandler):
    async def handle(self, message: CancelAllOrdersMessage) -> None:
        await self._client.cancel_all_orders(
            trading_pair=message.trading_pair,
        )
