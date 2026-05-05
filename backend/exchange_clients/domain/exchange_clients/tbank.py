"""T-Bank Invest gRPC клиент.

Особенности (отличается от ccxt-биржevykh клиентов):
- gRPC вместо REST/WS, библиотека `t-tech-investments` (`from t_tech.invest import ...`).
- Идентификатор инструмента — FIGI; используем поле TradingPair.symbol для FIGI.
- Объём ордера измеряется в **лотах** (целое); конвертация amount→quantity = int(amount).
- account_id обязателен для всех trading-операций; передаётся через init.
- Для market-data можно работать без api_key (sandbox/публичный gRPC), но T-Bank
  требует токен почти везде. Если token пустой — fetch_trading_pairs/fetch_candles
  всё равно понадобится валидный demo-токен.
- Margin/leverage не применимы для акций — соответствующие методы NotImplementedError.
"""

import asyncio
import contextlib
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from loguru import logger
from t_tech.invest import (
    AsyncClient,
    CandleInstrument,
    CandleInterval,
    InstrumentStatus,
    OrderDirection,
    Quotation,
    SubscriptionInterval,
)
from t_tech.invest import OrderType as TBankOrderType
from t_tech.invest.async_services import AsyncMarketDataStreamManager
from t_tech.invest.constants import INVEST_GRPC_API, INVEST_GRPC_API_SANDBOX
from t_tech.invest.schemas import IndicativesRequest
from t_tech.invest.utils import (
    decimal_to_quotation,
    money_to_decimal,
    quotation_to_decimal,
)

from exchanges.domain import Candle, Timeframe, TradingPair
from exchanges.domain.exchanges.tbank import TBankExchange
from exchanges.domain.schemas import MarketType

from ..base import AbstractExchangeClient, ExchangeClientRegistry
from ..proxies import ExchangeClientProxy
from ..schemas import (
    ExchangeClientBalance,
    ExchangeClientOrder,
    MarginMode,
    OrderSide,
    OrderStatus,
    OrderType,
)

_TIMEFRAME_TO_INTERVAL: dict[Timeframe, CandleInterval] = {
    Timeframe.ONE_MINUTE: CandleInterval.CANDLE_INTERVAL_1_MIN,
    Timeframe.FIVE_MINUTES: CandleInterval.CANDLE_INTERVAL_5_MIN,
    Timeframe.FIFTEEN_MINUTES: CandleInterval.CANDLE_INTERVAL_15_MIN,
    Timeframe.ONE_HOUR: CandleInterval.CANDLE_INTERVAL_HOUR,
    Timeframe.FOUR_HOURS: CandleInterval.CANDLE_INTERVAL_4_HOUR,
    Timeframe.ONE_DAY: CandleInterval.CANDLE_INTERVAL_DAY,
    Timeframe.ONE_WEEK: CandleInterval.CANDLE_INTERVAL_WEEK,
}

# Жёсткие лимиты T-Bank API на диапазон (to - from_) для GetCandles per-interval.
# При превышении сервер возвращает INVALID_ARGUMENT.
_TIMEFRAME_MAX_RANGE: dict[Timeframe, timedelta] = {
    Timeframe.ONE_MINUTE: timedelta(days=1),
    Timeframe.FIVE_MINUTES: timedelta(days=1),
    Timeframe.FIFTEEN_MINUTES: timedelta(days=1),
    Timeframe.ONE_HOUR: timedelta(weeks=1),
    Timeframe.FOUR_HOURS: timedelta(weeks=1),
    Timeframe.ONE_DAY: timedelta(days=365),
    Timeframe.ONE_WEEK: timedelta(days=365),
}

_TIMEFRAME_TO_SUBSCRIPTION: dict[Timeframe, SubscriptionInterval] = {
    Timeframe.ONE_MINUTE: SubscriptionInterval.SUBSCRIPTION_INTERVAL_ONE_MINUTE,
    Timeframe.FIVE_MINUTES: SubscriptionInterval.SUBSCRIPTION_INTERVAL_FIVE_MINUTES,
    Timeframe.FIFTEEN_MINUTES: (
        SubscriptionInterval.SUBSCRIPTION_INTERVAL_FIFTEEN_MINUTES
    ),
    Timeframe.ONE_HOUR: SubscriptionInterval.SUBSCRIPTION_INTERVAL_ONE_HOUR,
    Timeframe.FOUR_HOURS: SubscriptionInterval.SUBSCRIPTION_INTERVAL_4_HOUR,
    Timeframe.ONE_DAY: SubscriptionInterval.SUBSCRIPTION_INTERVAL_ONE_DAY,
    Timeframe.ONE_WEEK: SubscriptionInterval.SUBSCRIPTION_INTERVAL_WEEK,
}


@ExchangeClientRegistry.register
class TBankExchangeClient(AbstractExchangeClient):
    """Клиент T-Bank Invest API (gRPC)."""

    def __init__(
        self,
        exchange: TBankExchange,
        api_key: str = "",
        account_id: str = "",
        demo: bool = False,
        proxy: ExchangeClientProxy | None = None,
    ):
        self.api_key = api_key
        self.account_id = account_id
        self.demo = demo
        self.proxy = proxy
        self.exchange = exchange
        self._target = INVEST_GRPC_API_SANDBOX if demo else INVEST_GRPC_API
        self._client_cm: AsyncClient | None = None
        # Сам gRPC-сервис не имеет интерфейса ccxt, поэтому self.client — это
        # объект Services из t_tech.invest, доступ к нему через __aenter__.
        self.client = None  # type: ignore[assignment]

        # Состояние MarketDataStream для watch_ohlcv (lazy-init на 1-м вызове)
        self._md_stream: AsyncMarketDataStreamManager | None = None
        self._md_stream_task: asyncio.Task | None = None
        self._md_lock = asyncio.Lock()
        self._candle_queues: dict[
            tuple[str, SubscriptionInterval], asyncio.Queue[Candle]
        ] = {}
        self._subscribed_candles: set[tuple[str, SubscriptionInterval]] = set()

    # --- lifecycle ---

    async def __aenter__(self) -> "TBankExchangeClient":
        self._client_cm = AsyncClient(token=self.api_key, target=self._target)
        services = await self._client_cm.__aenter__()
        self.client = services  # type: ignore[assignment]
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._stop_md_stream()
        if self._client_cm is not None:
            await self._client_cm.__aexit__(exc_type, exc, tb)
            self._client_cm = None
            self.client = None  # type: ignore[assignment]

    # --- helpers ---

    @staticmethod
    def _q_to_decimal(q: Quotation) -> Decimal:
        return Decimal(str(quotation_to_decimal(q)))

    @staticmethod
    def _money_to_decimal(m) -> Decimal:
        return Decimal(str(money_to_decimal(m)))

    # --- market data ---

    async def fetch_trading_pairs(self, market_type: MarketType) -> list[TradingPair]:
        """Загружает список инструментов через InstrumentsService.

        SPOT → акции (shares), FUTURES → срочные фьючерсы, INDEX → индексы
        (indicatives — IMOEX, RTSI и пр., только для подписки на цену,
        не торгуются напрямую).
        """
        if market_type == MarketType.SPOT:
            response = await self.client.instruments.shares(  # type: ignore[union-attr]
                instrument_status=InstrumentStatus.INSTRUMENT_STATUS_BASE,
            )
            instruments = response.instruments
        elif market_type == MarketType.FUTURES:
            response = await self.client.instruments.futures(  # type: ignore[union-attr]
                instrument_status=InstrumentStatus.INSTRUMENT_STATUS_BASE,
            )
            instruments = response.instruments
        elif market_type == MarketType.INDEX:
            response = await self.client.instruments.indicatives(  # type: ignore[union-attr]
                request=IndicativesRequest(),
            )
            instruments = response.instruments
        else:
            return []

        result: list[TradingPair] = []
        for inst in instruments:
            figi = getattr(inst, "figi", "") or ""
            ticker = getattr(inst, "ticker", "") or ""
            currency = getattr(inst, "currency", "") or ""
            # Отбраковываем инструменты без обязательных полей —
            # без figi (symbol) / ticker (base) / currency (quote) их
            # невозможно корректно сопоставить ни в TradingPair, ни в API.
            if not figi or not ticker or not currency:
                logger.debug(
                    f"TBankExchangeClient: пропускаем инструмент без обязательных "
                    f"полей (figi={figi!r}, ticker={ticker!r}, currency={currency!r})"
                )
                continue
            base = ticker
            quote = currency.upper()
            min_price_increment = self._q_to_decimal(
                getattr(inst, "min_price_increment", None) or Quotation(units=0, nano=0)
            )
            lot = Decimal(str(getattr(inst, "lot", 1) or 1))
            # Индексы не торгуются — используем флаги buy/sell_available_flag,
            # для shares/futures — api_trade_available_flag.
            if market_type == MarketType.INDEX:
                is_active = bool(
                    getattr(inst, "buy_available_flag", False)
                    or getattr(inst, "sell_available_flag", False)
                )
            else:
                is_active = bool(getattr(inst, "api_trade_available_flag", False))
            result.append(
                TradingPair(
                    name=f"{base}/{quote}",
                    # FIGI используем как symbol — единственный надёжный ID T-Bank
                    symbol=figi,
                    base_currency=base,
                    quote_currency=quote,
                    settle_currency=quote,
                    market_type=market_type,
                    min_amount=lot,
                    amount_precision=lot,
                    price_precision=min_price_increment
                    if min_price_increment
                    else None,
                    is_active=is_active,
                )
            )
        return result

    async def fetch_candles(
        self,
        trading_pair: TradingPair,
        timeframe: Timeframe,
        since: datetime | None = None,
        limit: int | None = None,
        params: dict | None = None,
    ) -> list[Candle]:
        interval = _TIMEFRAME_TO_INTERVAL[timeframe]
        to = datetime.now(UTC)
        if since is None:
            # T-Bank API ограничивает диапазон (to - from_) per-interval, а не
            # количеством свечей. Берём min(желаемый, лимит API), иначе сервер
            # возвращает INVALID_ARGUMENT.
            tf_delta = timeframe.timedelta()
            requested = (limit or self.exchange.max_candles_per_request) * tf_delta
            since = to - min(requested, _TIMEFRAME_MAX_RANGE[timeframe])
        response = await self.client.market_data.get_candles(  # type: ignore[union-attr]
            instrument_id=trading_pair.symbol,
            from_=since,
            to=to,
            interval=interval,
            limit=limit,
        )

        candles = response.candles or []
        if limit is not None:
            candles = candles[-limit:]

        return [
            Candle(
                dt_unix=int(c.time.timestamp() * 1000),
                open=self._q_to_decimal(c.open),
                high=self._q_to_decimal(c.high),
                low=self._q_to_decimal(c.low),
                close=self._q_to_decimal(c.close),
                volume=Decimal(str(c.volume)),
            )
            for c in candles
        ]

    # --- balances ---

    async def fetch_balances(
        self, market_type: MarketType
    ) -> list[ExchangeClientBalance]:
        """Возвращает кэш-балансы по валютам через OperationsService.GetPositions.

        Стоковые позиции (securities/futures) не возвращаются — это не «баланс»
        в крипто-смысле. Для портфеля используй отдельный метод (TODO).
        """
        if not self.account_id:
            return []
        response = await self.client.operations.get_positions(  # type: ignore[union-attr]
            account_id=self.account_id,
        )
        result: list[ExchangeClientBalance] = []
        for money in response.money or []:
            total = self._money_to_decimal(money)
            blocked = Decimal("0")
            for blk in response.blocked or []:
                if blk.currency == money.currency:
                    blocked = self._money_to_decimal(blk)
                    break
            result.append(
                ExchangeClientBalance(
                    market_type=market_type,
                    currency=money.currency.upper(),
                    free=total - blocked,
                    used=blocked,
                    total=total,
                    debt=Decimal("0"),
                )
            )
        return result

    # --- orders ---

    async def create_market_order(
        self,
        trading_pair: TradingPair,
        side: OrderSide,
        amount: Decimal,
        price: Decimal,
    ) -> ExchangeClientOrder:
        if not self.account_id:
            raise ValueError("account_id обязателен для торговых операций T-Bank")

        direction = (
            OrderDirection.ORDER_DIRECTION_BUY
            if side == OrderSide.BUY
            else OrderDirection.ORDER_DIRECTION_SELL
        )
        # T-Bank quantity — целое число лотов
        quantity = int(amount)
        if quantity <= 0:
            raise ValueError(f"quantity должен быть >= 1 лота (получено {amount})")

        response = await self.client.orders.post_order(  # type: ignore[union-attr]
            instrument_id=trading_pair.symbol,
            quantity=quantity,
            direction=direction,
            account_id=self.account_id,
            order_type=TBankOrderType.ORDER_TYPE_MARKET,
            price=decimal_to_quotation(Decimal(price)),
        )
        order_price = self._money_to_decimal(response.executed_order_price)
        order_amount = Decimal(str(response.lots_executed))

        return ExchangeClientOrder(
            exchange_order_id=response.order_id,
            trading_pair=trading_pair,
            side=side,
            status=OrderStatus.CLOSED,
            type=OrderType.MARKET,
            timestamp=datetime.now(UTC),
            amount=order_amount,
            price=order_price,
            cost=self._money_to_decimal(response.total_order_amount),
            fee=self._money_to_decimal(response.executed_commission),
        )

    async def fetch_order(
        self,
        exchange_order_id: str,
        trading_pair: TradingPair,
    ) -> ExchangeClientOrder:
        if not self.account_id:
            raise ValueError("account_id обязателен для fetch_order T-Bank")
        response = await self.client.orders.get_order_state(  # type: ignore[union-attr]
            account_id=self.account_id,
            order_id=exchange_order_id,
        )
        side = (
            OrderSide.BUY if response.direction.name.endswith("BUY") else OrderSide.SELL
        )
        order_price = self._money_to_decimal(response.executed_order_price)
        order_amount = Decimal(str(response.lots_executed))
        return ExchangeClientOrder(
            exchange_order_id=response.order_id,
            trading_pair=trading_pair,
            side=side,
            status=OrderStatus.CLOSED
            if response.lots_executed == response.lots_requested
            else OrderStatus.OPENED,
            type=OrderType.MARKET,
            timestamp=response.order_date or datetime.now(UTC),
            amount=order_amount,
            price=order_price,
            cost=self._money_to_decimal(response.total_order_amount),
            fee=self._money_to_decimal(response.executed_commission),
        )

    async def cancel_all_orders(self, trading_pair: TradingPair) -> None:
        if not self.account_id:
            raise ValueError("account_id обязателен для cancel_all_orders T-Bank")
        orders = await self.client.orders.get_orders(  # type: ignore[union-attr]
            account_id=self.account_id,
        )
        for order in orders.orders:
            if order.figi == trading_pair.symbol:
                await self.client.orders.cancel_order(  # type: ignore[union-attr]
                    account_id=self.account_id,
                    order_id=order.order_id,
                )

    # --- streaming (gRPC MarketDataStream) ---

    async def watch_ohlcv(
        self,
        trading_pair: TradingPair,
        timeframe: Timeframe,
    ) -> list[Candle]:
        """Push-подписка на свечу через gRPC MarketDataStream.

        T-Bank вместо ccxt.pro pull-модели использует bidirectional gRPC stream:
        подписываемся один раз, читаем сообщения по мере поступления. Контракт
        `watch_ohlcv` (вызов в цикле, возврат свежих свечей) поверх этого
        реализуем буферизацией в asyncio.Queue per (figi, interval).
        """
        figi = trading_pair.symbol
        interval = _TIMEFRAME_TO_SUBSCRIPTION[timeframe]
        key = (figi, interval)

        async with self._md_lock:
            if self._md_stream is None:
                await self._init_md_stream()
            if key not in self._subscribed_candles:
                self._candle_queues[key] = asyncio.Queue()
                self._md_stream.candles.waiting_close(True).subscribe(  # type: ignore[union-attr]
                    [CandleInstrument(instrument_id=figi, interval=interval)]
                )
                self._subscribed_candles.add(key)

        candle = await self._candle_queues[key].get()
        return [candle]

    async def _init_md_stream(self) -> None:
        if self.client is None:
            raise RuntimeError(
                "TBankExchangeClient не инициализирован — используй `async with`"
            )
        self._md_stream = self.client.create_market_data_stream()  # type: ignore[union-attr]
        self._md_stream_task = asyncio.create_task(self._md_stream_loop())

    async def _md_stream_loop(self) -> None:
        if self._md_stream is None:
            return
        try:
            async for response in self._md_stream:
                tb_candle = getattr(response, "candle", None)
                if tb_candle is None:
                    continue
                key = (tb_candle.figi, tb_candle.interval)
                queue = self._candle_queues.get(key)
                if queue is None:
                    continue
                try:
                    candle = Candle(
                        dt_unix=int(tb_candle.time.timestamp() * 1000),
                        open=self._q_to_decimal(tb_candle.open),
                        high=self._q_to_decimal(tb_candle.high),
                        low=self._q_to_decimal(tb_candle.low),
                        close=self._q_to_decimal(tb_candle.close),
                        volume=Decimal(str(tb_candle.volume)),
                    )
                except Exception as e:
                    logger.warning(
                        f"TBankExchangeClient: ошибка маппинга candle "
                        f"figi={tb_candle.figi}: {e}"
                    )
                    continue
                await queue.put(candle)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"TBankExchangeClient MarketDataStream error: {e}")

    async def _stop_md_stream(self) -> None:
        if self._md_stream is not None:
            try:
                self._md_stream.stop()
            except Exception as e:
                logger.warning(f"TBankExchangeClient stop_md_stream: {e}")
        if self._md_stream_task is not None:
            self._md_stream_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._md_stream_task
            self._md_stream_task = None
        self._md_stream = None
        self._subscribed_candles.clear()
        self._candle_queues.clear()

    # --- not applicable for stocks ---

    async def set_margin_mode(
        self,
        margin_mode: MarginMode,
        trading_pair: TradingPair,
    ) -> None:
        raise NotImplementedError(
            "Маржинальные режимы не настраиваются через T-Bank API"
        )

    async def set_leverage(
        self,
        leverage: float,
        trading_pair: TradingPair,
    ) -> None:
        raise NotImplementedError("Кредитное плечо не настраивается через T-Bank API")


async def _fetch_all_pairs(api_key: str, demo: bool = True) -> None:
    exchange = TBankExchange(name="T-Bank", client_class_name="TBankExchangeClient")
    async with TBankExchangeClient(
        exchange=exchange, api_key=api_key, demo=demo
    ) as client:
        spot = await client.fetch_trading_pairs(MarketType.SPOT)
        futures = await client.fetch_trading_pairs(MarketType.FUTURES)

    print(f"Акции (SPOT):     {len(spot)}")
    print(f"Фьючерсы (FUTURES): {len(futures)}")
    print()
    print(f"{'FIGI':14}  {'Name':25}  {'Lot':>10}  {'Tick':>14}  Active")
    print("-" * 80)
    for p in (*spot, *futures):
        print(
            f"{p.symbol:14}  {p.name:25}  "
            f"{p.min_amount!s:>10}  "
            f"{p.price_precision or '-'!s:>14}  "
            f"{p.is_active}"
        )


if __name__ == "__main__":
    token = os.environ.get("TBANK_TOKEN")
    if not token:
        raise SystemExit("TBANK_TOKEN env var is required")
    asyncio.run(_fetch_all_pairs(api_key=token, demo=True))
