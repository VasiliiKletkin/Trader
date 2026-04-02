"""Загрузчики из БД: клиенты пула и WS-стримы."""

from functools import partial

from asgiref.sync import sync_to_async
from django.conf import settings
from loguru import logger

from arbitrage_traders.models import ArbitrageTrader
from arbitrage_traders.schemas import ArbitrageTraderStatus
from candle_sources.domain.ws.redis_cache import CandleRedisCache
from candle_sources.models import CandleSource, CandleSourceError, CandleSourceMode
from exchange_clients.domain.managers import ClientEntry
from exchange_clients.domain.streams import (
    BalanceStream,
    BaseStream,
    CandleStream,
    OrdersStream,
)
from exchange_clients.models import ExchangeClient, ExchangeClientBalance
from exchanges.domain import Candle, Timeframe
from exchanges.domain import Exchange as DomainExchange
from exchanges.domain import TradingPair as DomainTradingPair
from exchanges.models import Exchange, TradingPair
from telegram_bots.tasks import send_notification
from traders.models import Trader
from traders.schemas import TraderStatus


@sync_to_async
def load_clients() -> dict[int, ClientEntry]:
    """Загружает активных exchange client'ов для ExchangeClientPool."""
    clients: dict[int, ClientEntry] = {}
    for ec in ExchangeClient.active_objects.select_related("exchange", "proxy"):
        try:
            timestamps = [ec.updated_at, ec.exchange.updated_at]
            if ec.proxy:
                timestamps.append(ec.proxy.updated_at)
            updated_at = max(timestamps)
            clients[ec.pk] = (ec.instantiate(), updated_at)
        except Exception as e:
            logger.error(f"Не удалось создать клиент {ec.name} (pk={ec.pk}): {e}")
    return clients


def _get_candle_cache() -> CandleRedisCache:
    redis_settings = settings.REDIS
    return CandleRedisCache(
        host=str(redis_settings["HOST"]),
        port=int(redis_settings["PORT"]),
        db=int(redis_settings["EXCHANGE_CACHE_DATABASE"]),
        password=str(redis_settings["PASSWORD"])
        if redis_settings.get("PASSWORD")
        else None,
    )


_candle_cache: CandleRedisCache | None = None


async def _on_candle(
    exchange: DomainExchange,
    trading_pair: DomainTradingPair,
    timeframe: Timeframe,
    candle: Candle,
) -> None:
    global _candle_cache
    if _candle_cache is None:
        _candle_cache = _get_candle_cache()
    await _candle_cache.set_candle(
        exchange=exchange,
        trading_pair=trading_pair,
        timeframe=timeframe,
        candle=candle,
    )


@sync_to_async
def _on_candle_error(
    error: Exception,
    tb: str,
    source_id: int,
) -> None:
    error_type = type(error).__name__
    logger.error(
        f"CandleStream ошибка источника {source_id} [{error_type}]: {error}\n{tb}"
    )
    CandleSourceError.objects.create(
        candle_source_id=source_id,
        message=str(error),
        type=error_type,
        traceback=tb,
    )
    send_notification.delay(
        message=(
            f"WebSocket ошибка для источника {source_id}\n[{error_type}]: {error}"
        ),
    )


@sync_to_async
def load_candle_streams() -> dict[tuple, BaseStream]:
    """Загружает WS-стримы свечей для активных источников."""
    streams: dict[tuple, BaseStream] = {}
    sources = CandleSource.active_objects.filter(
        mode=CandleSourceMode.WEBSOCKET,
    ).select_related(
        "exchange_client",
        "exchange_client__exchange",
        "trading_pair",
    )
    for source in sources:
        cid = source.exchange_client_id
        domain_tp = source.trading_pair.instantiate(
            exchange=source.exchange_client.exchange,
        )
        stream = CandleStream(
            exchange_client_id=cid,
            trading_pair=domain_tp,
            timeframe=Timeframe(source.timeframe),
            on_candle=_on_candle,
            on_error=partial(_on_candle_error, source_id=source.pk),
        )
        streams[stream.key] = stream
    return streams


def _load_client_pairs() -> tuple[
    dict[int, set[int]], dict[int, TradingPair], dict[int, Exchange]
]:
    """Собирает (exchange_client_id → trading_pair_pks) для активных трейдеров."""
    client_ids: set[int] = set(
        Trader.objects.filter(
            status=TraderStatus.ENABLED,
        ).values_list("exchange_client_id", flat=True)
    )

    for left_id, right_id in ArbitrageTrader.objects.filter(
        status=ArbitrageTraderStatus.ENABLED,
    ).values_list(
        "left_exchange_client_id",
        "right_exchange_client_id",
    ):
        client_ids.add(left_id)
        client_ids.add(right_id)

    client_pairs: dict[int, set[int]] = {}
    tp_cache: dict[int, TradingPair] = {}
    exchange_cache: dict[int, Exchange] = {}

    for trader in Trader.objects.filter(
        status=TraderStatus.ENABLED,
        exchange_client_id__in=client_ids,
    ).select_related(
        "candle_source__trading_pair",
        "exchange_client__exchange",
    ):
        cid = trader.exchange_client_id
        tp = trader.candle_source.trading_pair
        client_pairs.setdefault(cid, set()).add(tp.pk)
        tp_cache[tp.pk] = tp
        exchange_cache[cid] = trader.exchange_client.exchange

    for arb_trader in ArbitrageTrader.objects.filter(
        status=ArbitrageTraderStatus.ENABLED,
    ).select_related(
        "left_candle_source__trading_pair",
        "right_candle_source__trading_pair",
        "left_exchange_client__exchange",
        "right_exchange_client__exchange",
    ):
        left_tp = arb_trader.left_candle_source.trading_pair
        right_tp = arb_trader.right_candle_source.trading_pair

        left_cid = arb_trader.left_exchange_client_id
        right_cid = arb_trader.right_exchange_client_id

        client_pairs.setdefault(left_cid, set()).add(left_tp.pk)
        client_pairs.setdefault(right_cid, set()).add(right_tp.pk)

        tp_cache[left_tp.pk] = left_tp
        tp_cache[right_tp.pk] = right_tp
        exchange_cache[left_cid] = arb_trader.left_exchange_client.exchange
        exchange_cache[right_cid] = arb_trader.right_exchange_client.exchange

    return client_pairs, tp_cache, exchange_cache


@sync_to_async
def load_balance_streams() -> dict[tuple, BaseStream]:
    """Загружает стримы балансов для активных трейдеров."""
    client_pairs, tp_cache, exchange_cache = _load_client_pairs()
    streams: dict[tuple, BaseStream] = {}

    for cid, tp_pks in client_pairs.items():
        exchange = exchange_cache.get(cid)
        if exchange is None:
            continue
        on_error = partial(_on_error, exchange_client_id=cid)
        for tp_pk in tp_pks:
            domain_tp = tp_cache[tp_pk].instantiate(exchange=exchange)
            stream = BalanceStream(
                exchange_client_id=cid,
                trading_pair=domain_tp,
                on_balance=partial(_on_balance, exchange_client_id=cid),
                on_error=on_error,
            )
            streams[stream.key] = stream

    return streams


@sync_to_async
def load_order_streams() -> dict[tuple, BaseStream]:
    """Загружает стримы ордеров для активных трейдеров."""
    client_pairs, tp_cache, exchange_cache = _load_client_pairs()
    streams: dict[tuple, BaseStream] = {}

    for cid, tp_pks in client_pairs.items():
        exchange = exchange_cache.get(cid)
        if exchange is None:
            continue
        on_error = partial(_on_error, exchange_client_id=cid)
        for tp_pk in tp_pks:
            domain_tp = tp_cache[tp_pk].instantiate(exchange=exchange)
            stream = OrdersStream(
                exchange_client_id=cid,
                trading_pair=domain_tp,
                on_orders=partial(_on_orders, exchange_client_id=cid),
                on_error=on_error,
            )
            streams[stream.key] = stream

    return streams


@sync_to_async
def _on_balance(balance: dict, exchange_client_id: int) -> None:
    balances = [
        ExchangeClientBalance(
            exchange_client_id=exchange_client_id,
            currency=currency,
            free=values.get("free", 0) or 0,
            used=values.get("used", 0) or 0,
            total=values.get("total", 0) or 0,
            debt=values.get("debt", 0) or 0,
        )
        for currency, values in balance.items()
        if isinstance(values, dict)
        and values.get("total") is not None
        and float(values["total"]) > 0
    ]
    if balances:
        ExchangeClientBalance.objects.bulk_create(
            balances,
            update_conflicts=True,
            update_fields=[
                "free",
                "used",
                "debt",
                "total",
                "updated_at",
            ],
            unique_fields=[
                "exchange_client",
                "currency",
            ],
        )


@sync_to_async
def _on_orders(orders: list[dict], exchange_client_id: int) -> None:
    for order in orders:
        logger.info(
            f"WS ордер exchange_client_id={exchange_client_id} "
            f"{order.get('symbol')} {order.get('side')} "
            f"{order.get('amount')} @ {order.get('price')} "
            f"[{order.get('status')}]"
        )


@sync_to_async
def _on_error(error: Exception, tb: str, exchange_client_id: int) -> None:
    error_type = type(error).__name__
    logger.error(
        f"WS ошибка exchange_client_id={exchange_client_id} "
        f"[{error_type}]: {error}\n{tb}"
    )
    send_notification.delay(
        message=(
            f"WS ошибка exchange_client_id={exchange_client_id}\n"
            f"[{error_type}]: {error}"
        ),
    )
