import asyncio
from collections import defaultdict
from typing import Dict, List, Optional
from celery import shared_task
from exchange_clients.domain.base import AbstractExchangeClient as DomainExchangeClient
from exchange_clients.models import ExchangeClient, ExchangeClientCandleSource
from core.utils.celery import run_tasks_in_groups
from core.utils.types import Timeframe, TraderStatus
from loguru import logger
from django.utils import timezone
from traders.models import Trader
from celery import group
from traders.domain import Trader as DomainTrader
from exchanges.domain import Candle as DomainCandle


@shared_task()
def handle_candle_by_sources(sources_ids: List[int]):
    """Контроль открытых позиций для всех активных трейдеров на основе источников."""

    sources = ExchangeClientCandleSource.objects.filter(
        id__in=sources_ids
    ).select_related(
        "exchange_client",
        "trading_pair",
    )
    traders = Trader.objects.filter(
        exchange_client__exchange__in=[s.exchange_client.exchange for s in sources],
        trading_pair__in=[s.trading_pair for s in sources],
        status=TraderStatus.ENABLED,
    ).select_related(
        "exchange_client",
        "trading_pair",
    )

    traders_by_clients = defaultdict(list)
    for trader in traders:
        exchange_client = trader.exchange_client
        traders_by_clients[exchange_client.pk].append(trader.pk)

    trader_group = group(
        handle_candle_for_exchange_client.s(
            exchange_client_id=exchange_client_id, traders_ids=traders_ids
        )
        for exchange_client_id, traders_ids in traders_by_clients.items()
    )
    trader_group.apply_async()


@shared_task()
def handle_candle_for_exchange_client(
    exchange_client_id: int,
    traders_ids: List[int],
):
    """Обработка свечи для трейдеров конкретного exchange_client."""
    exchange_client: ExchangeClient = ExchangeClient.active_objects.select_related(
        "exchange"
    ).get(id=exchange_client_id)
    traders = Trader.objects.filter(
        id__in=traders_ids,
        exchange_client=exchange_client,
        status=TraderStatus.ENABLED,
    ).select_related("exchange_client", "trading_pair")

    domain_exchange_client = exchange_client.instantiate()
    domain_traders: Dict[Trader, DomainTrader] = {}

    tasks = []
    for trader in traders:
        domain_trader = trader.instantiate(
            domain_exchange_client=domain_exchange_client
        )
        trader.load(trader=domain_trader)
        domain_traders[trader] = domain_trader

        current_candle, previous_candle = (
            list(trader.candles.order_by("-timestamp")[:2]) + [None, None]
        )[:2]

        if previous_candle and trader.has_existing_signal(previous_candle):
            tasks.append(
                trader_check_opened_positions_async(
                    trader=domain_trader,
                    candle=current_candle,
                    create_order=True,
                )
            )
        else:
            tasks.append(
                trader_handle_candle_async(
                    trader=domain_trader,
                    candle=previous_candle,
                    create_order=True,
                )
            )

    async def run_tasks(
        tasks: List[asyncio.Task],
        domain_exchange_client: DomainExchangeClient,
    ):
        async with domain_exchange_client:
            await asyncio.gather(*tasks)

    asyncio.run(
        run_tasks(
            tasks=tasks,
            domain_exchange_client=domain_exchange_client,
        )
    )

    for trader, domain_trader in domain_traders.items():
        trader.sync(trader=domain_trader)


async def trader_check_opened_positions_async(
    trader: DomainTrader,
    candle: Optional[DomainCandle],
    create_order: bool = True,
):
    try:
        if candle is None:
            logger.warning(f"Не удалось получить свечу для трейдера {trader}.")
            return
        await trader.check_opened_positions(candle=candle, create_order=create_order)
    except Exception as e:
        logger.error(f"Ошибка в check_opened_positions для трейдера {trader}: {e}")


async def trader_handle_candle_async(
    trader: DomainTrader,
    candle: Optional[DomainCandle],
    create_order: bool = True,
):
    try:
        if candle is None:
            logger.warning(f"Не удалось получить свечу для трейдера {trader}.")
            return
        await trader.handle_candle(candle=candle, create_order=create_order)
    except Exception as e:
        logger.error(f"Ошибка в handle_candle для трейдера {trader}: {e}")


# @shared_task()
# def traders_check_opened_positions(timeframe: str):
#     """Контроль открытых позиций для всех активных трейдеров."""
#     tf = Timeframe(timeframe)
#     trader_ids = list(
#         Trader.objects.filter(timeframe=tf, status=TraderStatus.ENABLED).values_list(
#             "pk", flat=True
#         )
#     )
#     task_params = [{"trader_id": trader_id} for trader_id in trader_ids]
#     run_tasks_in_groups(trader_check_opened_positions, task_params, chunk_size=20)


# @shared_task()
# def trader_check_opened_positions(trader_id: int):
#     try:
#         trader = Trader.objects.select_related(
#             "exchange_client",
#             "trading_pair",
#         ).get(id=trader_id)
#         candle = trader.candles.order_by("-timestamp").first()
#         if candle is None:
#             logger.warning(f"Не удалось получить свечу для трейдера {trader.pk}")
#             return
#         trader.check_opened_positions(candle=candle)
#     except Trader.DoesNotExist:
#         logger.error(f"Trader с id {trader_id} не существует.")
#     except Exception as e:
#         logger.error(
#             f"Ошибка при проверке открытых позиций для трейдера {trader_id}: {e}"
#         )


# @shared_task()
# def traders_handle_candle(timeframe: str):
#     """
#     Функция для запуска торгового цикла для всех трейдеров
#     на заданном таймфрейме.
#     """
#     tf = Timeframe(timeframe)
#     trader_ids = list(
#         Trader.objects.filter(timeframe=tf, status=TraderStatus.ENABLED).values_list(
#             "pk", flat=True
#         )
#     )
#     task_params = [{"trader_id": trader_id} for trader_id in trader_ids]
#     run_tasks_in_groups(trader_handle_candle, task_params, chunk_size=20)


# @shared_task()
# def trader_handle_candle(trader_id: int):
#     try:
#         trader = Trader.objects.select_related(
#             "exchange_client",
#             "trading_pair",
#             "strategy",
#             "risk_manager",
#         ).get(id=trader_id)
#         now = timezone.now()
#         tf_timedelta = Timeframe(trader.timeframe).timedelta()
#         candle = trader.get_candle_at_time(now - tf_timedelta)
#         if candle is None:
#             logger.warning(f"Не удалось получить свечу для трейдера {trader.pk}")
#             return
#         trader.handle_candle(candle=candle)
#     except Trader.DoesNotExist:
#         logger.error(f"Trader с id {trader_id} не существует.")
#     except Exception as e:
#         logger.error(
#             f"Ошибка при проверке открытых позиций для трейдера {trader_id}: {e}"
#         )


@shared_task(queue="trader_reboot")
def trader_reboot(trader_id: int):
    try:
        trader = Trader.objects.get(id=trader_id)
    except Trader.DoesNotExist:
        logger.error(f"Trader с id {trader_id} не существует.")
    trader.reboot()
