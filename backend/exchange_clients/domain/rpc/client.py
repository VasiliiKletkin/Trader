"""RPC-прокси для exchange_client. Отправляет команды через bus."""

from datetime import datetime
from decimal import Decimal

from core.utils.rpc import AbstractBusClient
from exchange_clients.domain.base import AbstractExchangeClient
from exchange_clients.domain.rpc.messages import (
    CancelAllOrdersMessage,
    CreateMarketOrderMessage,
    CreateMarketOrderResult,
    FetchBalancesMessage,
    FetchBalancesResult,
    FetchCandlesMessage,
    FetchCandlesResult,
    FetchOrderMessage,
    FetchOrderResult,
    FetchTradingPairsMessage,
    FetchTradingPairsResult,
    SetLeverageMessage,
    SetMarginModeMessage,
)
from exchange_clients.domain.schemas import (
    ExchangeClientBalance,
    ExchangeClientOrder,
    MarginMode,
    OrderSide,
)
from exchanges.domain import Candle, Exchange, Timeframe, TradingPair
from exchanges.domain.schemas import MarketType


class RPCExchangeClient(AbstractExchangeClient):
    """Лёгкий прокси: хранит id и bus_client, делегирует вызовы через шину."""

    def __init__(
        self,
        id: int,
        bus_client: AbstractBusClient,
        exchange: Exchange,
    ) -> None:
        self.id = id
        self.bus_client = bus_client
        self.exchange = exchange

    async def __aenter__(self) -> "RPCExchangeClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        pass

    async def fetch_trading_pairs(self, market_type: MarketType) -> list[TradingPair]:
        result: FetchTradingPairsResult = await self.bus_client.execute(  # type: ignore[assignment]
            FetchTradingPairsMessage(
                exchange_client_id=self.id,
                market_type=market_type,
            ),
        )
        return result.trading_pairs

    async def create_market_order(
        self,
        trading_pair: TradingPair,
        side: OrderSide,
        amount: Decimal,
        price: Decimal,
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

    async def fetch_balances(
        self, market_type: MarketType
    ) -> list[ExchangeClientBalance]:
        result: FetchBalancesResult = await self.bus_client.execute(  # type: ignore[assignment]
            FetchBalancesMessage(
                exchange_client_id=self.id,
                market_type=market_type,
            ),
        )
        return result.balances

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
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[Candle]:
        result: FetchCandlesResult = await self.bus_client.execute(  # type: ignore[assignment]
            FetchCandlesMessage(
                exchange_client_id=self.id,
                trading_pair=trading_pair,
                timeframe=timeframe,
                since=since,
                limit=limit,
            ),
        )
        return result.candles

    async def set_margin_mode(
        self,
        margin_mode: MarginMode,
        trading_pair: TradingPair,
    ) -> None:
        await self.bus_client.execute(
            SetMarginModeMessage(
                exchange_client_id=self.id,
                margin_mode=margin_mode,
                trading_pair=trading_pair,
            ),
        )

    async def set_leverage(
        self,
        leverage: float,
        trading_pair: TradingPair,
    ) -> None:
        await self.bus_client.execute(
            SetLeverageMessage(
                exchange_client_id=self.id,
                leverage=leverage,
                trading_pair=trading_pair,
            ),
        )
