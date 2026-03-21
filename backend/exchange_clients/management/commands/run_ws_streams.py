import asyncio
from functools import partial

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand
from loguru import logger

from arbitrage_traders.models import ArbitrageTrader
from arbitrage_traders.schemas import ArbitrageTraderStatus
from candle_sources.domain.ws.redis_cache import CandleRedisCache
from candle_sources.models import CandleSource, CandleSourceError, CandleSourceMode
from exchange_clients.domain import AbstractExchangeClient as DomainExchangeClient
from exchange_clients.domain.ws.manager import ExchangeConnection, StreamManager
from exchange_clients.domain.ws.redis_cache import BalanceRedisCache, OrdersRedisCache
from exchange_clients.domain.ws.streams import (
    BalanceStream,
    OHLCVStream,
    OrdersStream,
)
from exchange_clients.models import ExchangeClient
from exchanges.domain import Candle, Exchange, Timeframe, TradingPair
from exchanges.models import TradingPair as TradingPairModel
from telegram_bots.tasks import send_notification
from traders.models import Trader
from traders.schemas import TraderStatus

SYNC_INTERVAL = 60 * 10


class Command(BaseCommand):
    help = "Запускает все WebSocket стримы (свечи, балансы, ордера)"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        redis_settings = settings.REDIS
        redis_kwargs = {
            "host": redis_settings["HOST"],
            "port": int(redis_settings["PORT"]),
            "db": int(redis_settings["EXCHANGE_CACHE_DATABASE"]),
            "password": redis_settings.get("PASSWORD") or None,
        }
        self.candle_cache = CandleRedisCache(**redis_kwargs)
        self.balance_cache = BalanceRedisCache(**redis_kwargs)
        self.orders_cache = OrdersRedisCache(**redis_kwargs)

    def handle(self, *args, **options):
        self.stdout.write("Запуск всех WebSocket стримов...")
        manager = StreamManager(
            load_connections=self._load_connections,
            sync_interval=SYNC_INTERVAL,
        )
        asyncio.run(manager.run())

    @sync_to_async
    def _load_connections(
        self,
    ) -> dict[int, ExchangeConnection]:
        clients: dict[int, DomainExchangeClient] = {}
        streams: dict[int, list] = {}

        # 1. Свечи от WS candle sources
        self._load_candle_streams(clients, streams)

        # # 2. Балансы и ордера от трейдеров
        # self._load_trader_streams(clients, streams)

        return {
            cid: ExchangeConnection(
                exchange_client=clients[cid],
                streams=streams[cid],
            )
            for cid in clients
            if streams.get(cid)
        }

    def _load_candle_streams(
        self,
        clients: dict[int, DomainExchangeClient],
        streams: dict[int, list],
    ) -> None:
        sources = CandleSource.active_objects.filter(
            mode=CandleSourceMode.WEBSOCKET,
        ).select_related(
            "exchange_client",
            "exchange_client__exchange",
            "exchange_client__proxy",
            "trading_pair",
        )

        for source in sources:
            cid = source.exchange_client_id
            if cid not in clients:
                clients[cid] = source.exchange_client.instantiate()
                streams[cid] = []

            domain_source = source.instantiate(domain_exchange_client=clients[cid])
            streams[cid].append(
                OHLCVStream(
                    trading_pair=domain_source.trading_pair,
                    timeframe=domain_source.timeframe,
                    on_candle=self._on_candle,
                    on_error=partial(
                        self._on_candle_error,
                        source_id=source.pk,
                    ),
                )
            )

    def _load_trader_streams(
        self,
        clients: dict[int, DomainExchangeClient],
        streams: dict[int, list],
    ) -> None:
        # Собираем exchange_client_id от активных трейдеров
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

        # Загружаем клиентов (если ещё не загружены)
        for ec in ExchangeClient.objects.filter(
            pk__in=client_ids,
        ).select_related("exchange", "proxy"):
            if ec.pk not in clients:
                clients[ec.pk] = ec.instantiate()
                streams[ec.pk] = []

        # Собираем (exchange_client_id, trading_pair) пары
        client_pairs: dict[tuple[int, int], TradingPairModel] = {}
        for trader in Trader.objects.filter(
            status=TraderStatus.ENABLED,
            exchange_client_id__in=client_ids,
        ).select_related("candle_source__trading_pair"):
            cid = trader.exchange_client_id
            tp = trader.candle_source.trading_pair
            client_pairs[(cid, tp.pk)] = tp

        for arb_trader in ArbitrageTrader.objects.filter(
            status=ArbitrageTraderStatus.ENABLED,
        ).select_related(
            "left_candle_source__trading_pair",
            "right_candle_source__trading_pair",
        ):
            left_tp = arb_trader.left_candle_source.trading_pair
            right_tp = arb_trader.right_candle_source.trading_pair
            client_pairs[(arb_trader.left_exchange_client_id, left_tp.pk)] = left_tp
            client_pairs[(arb_trader.right_exchange_client_id, right_tp.pk)] = right_tp

        for (cid, _), orm_tp in client_pairs.items():
            if cid not in clients:
                continue

            domain_tp = orm_tp.instantiate()
            on_error = partial(
                self._on_trader_error,
                exchange_client_id=cid,
            )

            if cid not in streams:
                streams[cid] = []

            streams[cid].append(
                BalanceStream(
                    trading_pair=domain_tp,
                    on_balance=partial(
                        self._on_balance,
                        exchange_client_id=cid,
                    ),
                    on_error=on_error,
                )
            )
            streams[cid].append(
                OrdersStream(
                    trading_pair=domain_tp,
                    on_orders=partial(
                        self._on_orders,
                        exchange_client_id=cid,
                    ),
                    on_error=on_error,
                )
            )

    # -- Колбэки свечей --

    async def _on_candle(
        self,
        exchange: Exchange,
        trading_pair: TradingPair,
        timeframe: Timeframe,
        candle: Candle,
    ) -> None:
        await self.candle_cache.set_candle(
            exchange=exchange,
            trading_pair=trading_pair,
            timeframe=timeframe,
            candle=candle,
        )

    @sync_to_async
    def _on_candle_error(self, error: Exception, tb: str, source_id: int) -> None:
        error_type = type(error).__name__
        logger.error(
            f"WS ошибка для источника {source_id} [{error_type}]: {error}\n{tb}"
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

    # -- Колбэки трейдеров --

    async def _on_balance(self, balance: dict, exchange_client_id: int) -> None:
        await self.balance_cache.set_balance(
            exchange_client_id=exchange_client_id,
            balance=balance,
        )

    async def _on_orders(
        self,
        orders: list[dict],
        exchange_client_id: int,
    ) -> None:
        if orders:
            symbol = orders[0].get("symbol", "unknown")
            await self.orders_cache.set_orders(
                exchange_client_id=exchange_client_id,
                symbol=symbol,
                orders=orders,
            )

    @sync_to_async
    def _on_trader_error(
        self, error: Exception, tb: str, exchange_client_id: int
    ) -> None:
        error_type = type(error).__name__
        logger.error(
            f"WS ошибка exchange_client_id="
            f"{exchange_client_id} "
            f"[{error_type}]: {error}\n{tb}"
        )
        send_notification.delay(
            message=(
                f"WS ошибка exchange_client_id="
                f"{exchange_client_id}\n"
                f"[{error_type}]: {error}"
            ),
        )
