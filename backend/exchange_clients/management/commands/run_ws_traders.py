import asyncio
from functools import partial

from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand
from loguru import logger

from arbitrage_traders.models import ArbitrageTrader
from arbitrage_traders.schemas import ArbitrageTraderStatus
from exchange_clients.domain import AbstractExchangeClient as DomainExchangeClient
from exchange_clients.domain.ws.manager import ExchangeConnection, StreamWorker
from exchange_clients.domain.ws.streams import (
    BalanceStream,
    OrdersStream,
)
from exchange_clients.models import ExchangeClient, ExchangeClientBalance
from exchanges.models import Exchange, TradingPair
from telegram_bots.tasks import send_notification
from traders.models import Trader
from traders.schemas import TraderStatus


class Command(BaseCommand):
    help = "Запускает WebSocket стримы для отслеживания балансов и ордеров"

    def handle(self, *args, **options):
        self.stdout.write("Запуск WebSocket стримов трейдеров...")
        manager = StreamWorker(
            load_connections=self._load_connections,
            sync_interval=60,
        )
        asyncio.run(manager.run())

    @sync_to_async
    def _load_connections(
        self,
    ) -> dict[int, ExchangeConnection]:
        # Собираем exchange_client_id от активных трейдеров
        client_ids: set[int] = set(
            Trader.objects.filter(
                status=TraderStatus.ENABLED,
            ).values_list("exchange_client_id", flat=True)
        )

        # От арбитражных трейдеров
        for left_id, right_id in ArbitrageTrader.objects.filter(
            status=ArbitrageTraderStatus.ENABLED,
        ).values_list(
            "left_exchange_client_id",
            "right_exchange_client_id",
        ):
            client_ids.add(left_id)
            client_ids.add(right_id)

        # Загружаем клиентов
        clients: dict[int, DomainExchangeClient] = {}
        client_exchanges: dict[int, Exchange] = {}
        for ec in ExchangeClient.objects.filter(
            pk__in=client_ids,
        ).select_related("exchange", "proxy"):
            clients[ec.pk] = ec.instantiate()
            client_exchanges[ec.pk] = ec.exchange

        # Собираем (exchange_client_id, trading_pair) пары
        client_pairs: dict[tuple[int, int], TradingPair] = {}
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

        # Строим connections
        streams: dict[int, list] = {}

        for (cid, _), orm_tp in client_pairs.items():
            if cid not in clients:
                continue

            domain_tp = orm_tp.instantiate(exchange=client_exchanges[cid])
            on_error = partial(self._on_error, exchange_client_id=cid)

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

        return {
            cid: ExchangeConnection(
                exchange_client=clients[cid],
                streams=streams[cid],
            )
            for cid in streams
        }

    @sync_to_async
    def _on_balance(self, balance: dict, exchange_client_id: int) -> None:
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
    def _on_orders(self, orders: list[dict], exchange_client_id: int) -> None:
        for order in orders:
            logger.info(
                f"WS ордер exchange_client_id="
                f"{exchange_client_id} "
                f"{order.get('symbol')} {order.get('side')} "
                f"{order.get('amount')} @ {order.get('price')} "
                f"[{order.get('status')}]"
            )

    @sync_to_async
    def _on_error(self, error: Exception, tb: str, exchange_client_id: int) -> None:
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
