import asyncio
import traceback

from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand
from loguru import logger

from arbitrage_traders.models import ArbitrageTrader
from arbitrage_traders.schemas import ArbitrageTraderStatus
from exchange_clients.domain import AbstractExchangeClient as DomainExchangeClient
from exchange_clients.domain.ws.manager import ExchangeClientStreamManager
from exchange_clients.models import ExchangeClient, ExchangeClientBalance
from telegram_bots.tasks import send_notification
from traders.models import Trader
from traders.schemas import TraderStatus


class Command(BaseCommand):
    help = "Запускает WebSocket стримы для отслеживания балансов и ордеров"

    def handle(self, *args, **options):
        self.stdout.write("Запуск WebSocket стримов клиентов бирж...")
        manager = ExchangeClientStreamManager(
            load_clients=self._load_clients,
            on_balance=self._on_balance,
            on_orders=self._on_orders,
            on_error=self._on_error,
            sync_interval=60,
        )
        asyncio.run(manager.run())

    @sync_to_async
    def _load_clients(self) -> dict[int, DomainExchangeClient]:
        # Собираем exchange_client_id от активных трейдеров
        trader_client_ids = set(
            Trader.objects.filter(status=TraderStatus.ENABLED).values_list(
                "exchange_client_id", flat=True
            )
        )

        # Собираем exchange_client_id от активных арбитражных трейдеров
        arb_traders = ArbitrageTrader.objects.filter(
            status=ArbitrageTraderStatus.ENABLED,
        ).values_list(
            "left_exchange_client_id",
            "right_exchange_client_id",
        )
        for left_id, right_id in arb_traders:
            trader_client_ids.add(left_id)
            trader_client_ids.add(right_id)

        # Загружаем и инстанцируем уникальных клиентов
        exchange_clients = ExchangeClient.objects.filter(
            pk__in=trader_client_ids,
        ).select_related("exchange", "proxy")

        return {client.pk: client.instantiate() for client in exchange_clients}

    @sync_to_async
    def _on_balance(self, exchange_client_id: int, balance: dict) -> None:
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
    def _on_orders(self, exchange_client_id: int, orders: list[dict]) -> None:
        for order in orders:
            logger.info(
                f"WS ордер exchange_client_id={exchange_client_id} "
                f"{order.get('symbol')} {order.get('side')} "
                f"{order.get('amount')} @ {order.get('price')} "
                f"[{order.get('status')}]"
            )

    @sync_to_async
    def _on_error(self, exchange_client_id: int, error: Exception) -> None:
        error_type = type(error).__name__
        logger.error(
            f"WS ошибка exchange_client_id={exchange_client_id} "
            f"[{error_type}]: {error}\n{traceback.format_exc()}"
        )
        send_notification.delay(
            message=(
                f"WS ошибка exchange_client_id="
                f"{exchange_client_id}\n"
                f"[{error_type}]: {error}"
            ),
        )
