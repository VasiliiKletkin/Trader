"""RPC-прокси для exchange_client. Отправляет команды через bus."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from core.utils.cqrs import AbstractBusClient
from exchange_clients.domain.base import AbstractExchangeClient
from exchange_clients.domain.messages.messages import (
    CancelAllOrdersMessage,
    CreateMarketOrderMessage,
    CreateMarketOrderResult,
    FetchBalancesMessage,
    FetchBalancesResult,
    FetchOrderMessage,
    FetchOrderResult,
    GetOpenOrdersMessage,
    GetOpenOrdersResult,
)
from exchange_clients.domain.schemas import (
    ExchangeClientBalance,
    ExchangeClientOrder,
    OrderSide,
)
from exchanges.domain import Candle, Timeframe, TradingPair


class RPCExchangeClient(AbstractExchangeClient):
    """Лёгкий прокси: хранит id и bus_client, делегирует вызовы через шину."""

    def __init__(self, id: int, bus_client: AbstractBusClient) -> None:
        self.id = id
        self.bus_client = bus_client

    async def create_market_order(
        self,
        trading_pair: TradingPair,
        side: OrderSide,
        amount: Decimal,
        price: Decimal,
        params: dict | None = None,
    ) -> ExchangeClientOrder:
        result: CreateMarketOrderResult = await self.bus_client.execute(  # type: ignore[assignment]
            CreateMarketOrderMessage(
                exchange_client_id=self.id,
                trading_pair=trading_pair,
                side=side,
                amount=amount,
                price=price,
            ),
        )
        return result.order

    async def get_balances(self) -> list[ExchangeClientBalance]:
        result: FetchBalancesResult = await self.bus_client.execute(  # type: ignore[assignment]
            FetchBalancesMessage(exchange_client_id=self.id),
        )
        return result.balances

    async def get_open_orders(
        self,
        trading_pair: TradingPair | None = None,
    ) -> list[dict[str, Any]]:
        result: GetOpenOrdersResult = await self.bus_client.execute(  # type: ignore[assignment]
            GetOpenOrdersMessage(
                exchange_client_id=self.id,
                trading_pair=trading_pair,
            ),
        )
        return result.orders  # type: ignore[return-value]

    async def fetch_order(
        self,
        exchange_order_id: str,
        trading_pair: TradingPair,
    ) -> ExchangeClientOrder:
        result: FetchOrderResult = await self.bus_client.execute(  # type: ignore[assignment]
            FetchOrderMessage(
                exchange_client_id=self.id,
                exchange_order_id=exchange_order_id,
                trading_pair=trading_pair,
            ),
        )
        return result.order

    async def cancel_all_orders(
        self,
        trading_pair: TradingPair,
    ) -> None:
        await self.bus_client.execute(
            CancelAllOrdersMessage(
                exchange_client_id=self.id,
                trading_pair=trading_pair,
            ),
        )

    async def fetch_candles(
        self,
        trading_pair: TradingPair,
        timeframe: Timeframe,
        since: datetime,
        limit: int,
    ) -> list[Candle]:
        raise NotImplementedError

    async def get_orders(
        self,
        trading_pair: TradingPair | None = None,
        since: int | None = None,
        limit: int | None = None,
        params: dict[str, Any] | None = None,
    ) -> list[ExchangeClientOrder]:
        raise NotImplementedError
