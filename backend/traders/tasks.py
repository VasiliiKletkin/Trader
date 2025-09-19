import asyncio
from collections import defaultdict
from typing import Dict, List
from celery import shared_task
from exchange_clients.domain.base import AbstractExchangeClient
from exchange_clients.models import ExchangeClient, ExchangeClientCandleSource
from core.utils.celery import run_tasks_in_groups
from core.utils.types import Timeframe, TraderStatus
from loguru import logger
from django.utils import timezone
from traders.models import Trader
from celery import group
from traders.domain import Trader as DomainTrader
from exchange_clients.domain import Candle as DomainCandle


@shared_task()
def check_opened_positions_based_on_sources(sources_ids: list[int]):
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
    ).select_related("exchange_client", "trading_pair")

    traders_by_clients = defaultdict(list)
    for trader in traders:
        exchange_client = trader.exchange_client
        traders_by_clients[exchange_client.pk].append(trader.pk)

    trader_group = group(
        check_opened_positions_for_exchange_client_traders.s(
            exchange_client_id=exchange_client_id, traders_ids=traders_ids
        )
        for exchange_client_id, traders_ids in traders_by_clients.items()
    )
    trader_group.apply_async()


@shared_task()
def check_opened_positions_for_exchange_client_traders(
    exchange_client_id: int,
    traders_ids: List[int],
):
    """Контроль открытых позиций для трейдеров конкретного exchange_client."""
    exchange_client: ExchangeClient = ExchangeClient.active_objects.select_related(
        "exchange"
    ).get(id=exchange_client_id)
    traders = Trader.objects.filter(
        id__in=traders_ids,
        exchange_client=exchange_client,
        status=TraderStatus.ENABLED,
    ).select_related(
        "exchange_client",
        "trading_pair",
    )

    domain_exchange_client = exchange_client.instantiate()

    domain_traders: Dict[Trader, DomainTrader] = {}
    domain_candles: Dict[DomainTrader, DomainCandle] = {}
    for trader in traders:
        domain_trader = trader.instantiate(
            domain_exchange_client=domain_exchange_client
        )
        trader.load(trader=domain_trader)
        domain_traders[trader] = domain_trader
        candle = trader.candles.order_by("-timestamp").first()
        if candle:
            domain_candles[domain_trader] = candle.instantiate()

    asyncio.run(
        process_domain_traders_opened_positions(
            change_client=domain_exchange_client,
            traders=domain_traders.values(),
            candles=domain_candles,
            create_order=True,
        )
    )
    for trader, domain_trader in domain_traders.items():
        trader.sync(trader=domain_trader)


async def process_domain_traders_opened_positions(
    exchange_client: AbstractExchangeClient,
    traders: List[DomainTrader],
    candles: Dict[int, DomainCandle],
    create_order: bool = True,
):
    async with exchange_client:
        await asyncio.gather(
            *[
                check_single_trader(
                    trader=trader,
                    candles=candles,
                    create_order=create_order,
                )
                for trader in traders
            ]
        )


async def check_single_trader(
    trader: DomainTrader,
    candles: Dict[int, DomainCandle],
    create_order: bool = True,
):
    try:
        candle = candles.get(trader)
        if candle is None:
            logger.warning(f"Не удалось получить свечу для трейдера {trader}.")
            return
        await trader.check_opened_positions(
            candle=candle,
            create_order=create_order,
        )
    except Exception as e:
        logger.error(f"Ошибка при проверке позиций для трейдера {trader}: {e}")


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


# @shared_task(queue="trader_reboot")
# def trader_reboot(trader_id: int):
#     try:
#         trader = Trader.objects.get(id=trader_id)
#         trader.reboot()
#     except Trader.DoesNotExist:
#         logger.error(f"Trader с id {trader_id} не существует.")
