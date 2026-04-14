"""Хендлеры сообщений для exchange worker."""

from core.utils.rpc import Handler, Registry
from exchange_clients.domain.base import AbstractExchangeClient

from .messages import (
    CancelAllOrdersMessage,
    CreateMarketOrderMessage,
    CreateMarketOrderResult,
    FetchBalancesMessage,
    FetchBalancesResult,
    FetchCandlesMessage,
    FetchCandlesResult,
    FetchOrderMessage,
    FetchOrderResult,
    SetLeverageMessage,
    SetMarginModeMessage,
)


class ExchangeClientHandler(Handler):
    """Базовый хендлер с exchange client в конструкторе."""

    def __init__(self, client: AbstractExchangeClient) -> None:
        self._client = client


@Registry.handler(FetchBalancesMessage, FetchBalancesResult)
class FetchBalancesHandler(ExchangeClientHandler):
    async def handle(self, message: FetchBalancesMessage) -> FetchBalancesResult:
        balances = await self._client.fetch_balances(
            market_type=message.market_type,
        )
        return FetchBalancesResult(balances=balances)


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


@Registry.handler(FetchOrderMessage, FetchOrderResult)
class FetchOrderHandler(ExchangeClientHandler):
    async def handle(self, message: FetchOrderMessage) -> FetchOrderResult:
        order = await self._client.fetch_order(
            exchange_order_id=message.exchange_order_id,
            trading_pair=message.trading_pair,
        )
        return FetchOrderResult(order=order)


@Registry.handler(CancelAllOrdersMessage)
class CancelAllOrdersHandler(ExchangeClientHandler):
    async def handle(self, message: CancelAllOrdersMessage) -> None:
        await self._client.cancel_all_orders(
            trading_pair=message.trading_pair,
        )


@Registry.handler(FetchCandlesMessage, FetchCandlesResult)
class FetchCandlesHandler(ExchangeClientHandler):
    async def handle(self, message: FetchCandlesMessage) -> FetchCandlesResult:
        candles = await self._client.fetch_candles(
            trading_pair=message.trading_pair,
            timeframe=message.timeframe,
            since=message.since,
            limit=message.limit,
        )
        return FetchCandlesResult(candles=candles)


@Registry.handler(SetMarginModeMessage)
class SetMarginModeHandler(ExchangeClientHandler):
    async def handle(self, message: SetMarginModeMessage) -> None:
        await self._client.set_margin_mode(
            margin_mode=message.margin_mode,
            trading_pair=message.trading_pair,
        )


@Registry.handler(SetLeverageMessage)
class SetLeverageHandler(ExchangeClientHandler):
    async def handle(self, message: SetLeverageMessage) -> None:
        await self._client.set_leverage(
            leverage=message.leverage,
            trading_pair=message.trading_pair,
        )
