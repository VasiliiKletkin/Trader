"""Management command: запуск trader WS worker (балансы/ордера)."""

import asyncio

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand
from loguru import logger

from arbitrage_traders.models import ArbitrageTrader
from arbitrage_traders.schemas import ArbitrageTraderStatus
from exchange_clients.domain.cache import ExchangeCache
from exchange_clients.domain.managers import (
    ClientEntry,
    ExchangeClientPool,
    StreamManager,
)
from exchange_clients.domain.streams import (
    BalanceStream,
    BaseStream,
    OrdersStream,
)
from exchange_clients.domain.workers import ExchangeClientStreamWorker
from exchange_clients.models import ExchangeClient
from exchanges.domain.schemas import MarketType
from exchanges.models import Exchange, TradingPair
from traders.models import Trader
from traders.schemas import TraderStatus

_exchange_cache = None


def _get_exchange_cache():
    global _exchange_cache
    if _exchange_cache is None:
        rs = settings.REDIS
        _exchange_cache = ExchangeCache(
            host=str(rs["HOST"]),
            port=int(rs["PORT"]),
            db=int(rs["EXCHANGE_CACHE_DATABASE"]),
            password=str(rs["PASSWORD"]) if rs.get("PASSWORD") else None,
        )
    return _exchange_cache


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
def load_streams() -> dict[tuple, BaseStream]:
    """Загружает стримы балансов и ордеров для активных трейдеров."""
    cache = _get_exchange_cache()
    client_pairs, tp_cache, exchange_cache = _load_client_pairs()
    streams: dict[tuple, BaseStream] = {}

    for cid, tp_pks in client_pairs.items():
        for market_type in MarketType:
            balance = BalanceStream(
                exchange_client_id=cid,
                market_type=market_type,
                cache=cache,
            )
            streams[balance.key] = balance

        exchange = exchange_cache.get(cid)
        if exchange is None:
            continue
        for tp_pk in tp_pks:
            domain_tp = tp_cache[tp_pk].instantiate(exchange=exchange)
            order = OrdersStream(
                exchange_client_id=cid,
                cache=cache,
                trading_pair=domain_tp,
            )
            streams[order.key] = order

    return streams


class Command(BaseCommand):
    help = "Запускает exchange client stream worker (WS балансы/ордера)"

    def handle(self, *args, **options):
        pool = ExchangeClientPool(loader=load_clients)
        stream_manager = StreamManager(pool=pool, load_streams=load_streams)
        worker = ExchangeClientStreamWorker(
            pool=pool,
            stream_manager=stream_manager,
        )
        asyncio.run(worker.launch())
