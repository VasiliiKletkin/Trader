"""Management command: запуск exchange client worker (REST + WS балансы/ордера)."""

import asyncio

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand
from loguru import logger

from arbitrage_traders.models import ArbitrageTrader
from arbitrage_traders.schemas import ArbitrageTraderStatus
from core.bus import create_redis_bus_broker
from exchange_clients.domain.managers import (
    ClientEntry,
    ExchangeClientPool,
    StreamManager,
)
from exchange_clients.domain.redis_cache import BalanceRedisCache, OrderRedisCache
from exchange_clients.domain.rpc.server import ExchangeClientRPCServer
from exchange_clients.domain.streams import (
    BalanceStream,
    BaseStream,
    OrdersStream,
)
from exchange_clients.domain.workers import ExchangeClientWorker
from exchange_clients.models import ExchangeClient
from exchanges.models import Exchange, TradingPair
from traders.models import Trader
from traders.schemas import TraderStatus

_balance_cache = None
_order_cache = None


def _get_balance_cache():
    global _balance_cache
    if _balance_cache is None:
        rs = settings.REDIS
        _balance_cache = BalanceRedisCache(
            host=str(rs["HOST"]),
            port=int(rs["PORT"]),
            db=int(rs["EXCHANGE_CACHE_DATABASE"]),
            password=str(rs["PASSWORD"]) if rs.get("PASSWORD") else None,
        )
    return _balance_cache


def _get_order_cache():
    global _order_cache
    if _order_cache is None:
        rs = settings.REDIS
        _order_cache = OrderRedisCache(
            host=str(rs["HOST"]),
            port=int(rs["PORT"]),
            db=int(rs["EXCHANGE_CACHE_DATABASE"]),
            password=str(rs["PASSWORD"]) if rs.get("PASSWORD") else None,
        )
    return _order_cache


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
            clients[ec.pk] = ClientEntry(ec.instantiate(), updated_at)
        except Exception as e:
            logger.error(f"Не удалось создать клиент {ec.name} (pk={ec.pk}): {e}")
    return clients


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
def load_balance_and_order_streams() -> dict[tuple, BaseStream]:
    """Загружает стримы балансов и ордеров для активных трейдеров."""
    balance_cache = _get_balance_cache()
    order_cache = _get_order_cache()
    client_pairs, tp_cache, exchange_cache = _load_client_pairs()
    streams: dict[tuple, BaseStream] = {}

    for cid, tp_pks in client_pairs.items():
        balance = BalanceStream(exchange_client_id=cid, cache=balance_cache)
        streams[balance.key] = balance

        exchange = exchange_cache.get(cid)
        if exchange is None:
            continue
        for tp_pk in tp_pks:
            domain_tp = tp_cache[tp_pk].instantiate(exchange=exchange)
            order = OrdersStream(
                exchange_client_id=cid,
                cache=order_cache,
                trading_pair=domain_tp,
            )
            streams[order.key] = order

    return streams


class Command(BaseCommand):
    help = "Запускает exchange client worker (REST + WS балансы/ордера)"

    def handle(self, *args, **options):
        pool = ExchangeClientPool(loader=load_clients)
        rpc_server = ExchangeClientRPCServer(
            broker=create_redis_bus_broker(),
            pool=pool,
        )
        stream_manager = StreamManager(
            pool=pool,
            load_streams=load_balance_and_order_streams,
        )
        worker = ExchangeClientWorker(
            pool=pool,
            stream_manager=stream_manager,
            rpc_server=rpc_server,
        )
        asyncio.run(worker.launch())
