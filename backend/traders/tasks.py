import asyncio
from collections import defaultdict
from typing import Dict, List, Optional
from celery import shared_task
from exchange_clients.domain.base import AbstractExchangeClient as DomainExchangeClient
from exchange_clients.models import ExchangeClient, ExchangeClientCandleSource
from core.utils.types import TraderStatus
from loguru import logger
from traders.models import Trader
from celery import group
from traders.domain import Trader as DomainTrader
from exchanges.domain import Candle as DomainCandle


@shared_task()
def handle_candle_by_sources(sources_ids: List[int]):
    """Контроль открытых позиций для всех активных трейдеров на основе источников."""
    logger.info(f"Начало обработки свечей для источников: {sources_ids}")

    sources = ExchangeClientCandleSource.objects.filter(
        id__in=sources_ids
    ).select_related(
        "exchange_client",
        "trading_pair",
    )
    logger.info(f"Найдено {len(sources)} источников")

    traders = Trader.objects.filter(
        exchange_client__exchange__in=[s.exchange_client.exchange for s in sources],
        trading_pair__in=[s.trading_pair for s in sources],
        status=TraderStatus.ENABLED,
    ).select_related(
        "exchange_client",
        "trading_pair",
    )
    logger.info(f"Найдено {len(traders)} активных трейдеров")

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
    logger.info(f"Запущено {len(traders_by_clients)} подзадач для exchange_clients")


@shared_task()
def handle_candle_for_exchange_client(
    exchange_client_id: int,
    traders_ids: List[int],
) -> None:
    """Обработка свечи для трейдеров конкретного exchange_client."""
    logger.info(f"Начало обработки свечей для exchange_client {exchange_client_id} с трейдерами {traders_ids}")

    exchange_client: ExchangeClient = ExchangeClient.active_objects.select_related(
        "exchange"
    ).get(id=exchange_client_id)
    traders = Trader.objects.filter(
        id__in=traders_ids,
        exchange_client=exchange_client,
        status=TraderStatus.ENABLED,
    ).select_related("exchange_client", "trading_pair")
    logger.info(f"Найдено {len(traders)} трейдеров для обработки")

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
                    candle=current_candle.instantiate() if current_candle else None,
                    create_order=True,
                )
            )
        else:
            tasks.append(
                trader_handle_candle_async(
                    trader=domain_trader,
                    candle=previous_candle.instantiate() if previous_candle else None,
                    create_order=True,
                )
            )

    asyncio.run(
        run_tasks_with_exchange_client(
            exchange_client=domain_exchange_client,
            tasks=tasks,
        )
    )

    for trader, domain_trader in domain_traders.items():
        trader.sync(trader=domain_trader)
    logger.info(f"Завершена обработка свечей для exchange_client {exchange_client_id}")


async def run_tasks_with_exchange_client(
    exchange_client: DomainExchangeClient,
    tasks: List[asyncio.Task],
):
    async with exchange_client:
        await asyncio.gather(*tasks)


async def trader_check_opened_positions_async(
    trader: DomainTrader,
    candle: Optional[DomainCandle],
    create_order: bool = True,
):
    logger.info(f"Начало проверки открытых позиций для трейдера {trader}")
    try:
        if candle is None:
            logger.warning(f"Не удалось получить свечу для трейдера {trader}.")
            return
        await trader.check_opened_positions(candle=candle, create_order=create_order)
        logger.info(f"Завершена проверка открытых позиций для трейдера {trader}")
    except Exception as e:
        logger.error(f"Ошибка в check_opened_positions для трейдера {trader}: {e}")


async def trader_handle_candle_async(
    trader: DomainTrader,
    candle: Optional[DomainCandle],
    create_order: bool = True,
):
    logger.info(f"Начало обработки свечи для трейдера {trader}")
    try:
        if candle is None:
            logger.warning(f"Не удалось получить свечу для трейдера {trader}.")
            return
        await trader.handle_candle(candle=candle, create_order=create_order)
        logger.info(f"Завершена обработка свечи для трейдера {trader}")
    except Exception as e:
        logger.error(f"Ошибка в handle_candle для трейдера {trader}: {e}")


@shared_task(queue="trader_reboot")
def trader_reboot(trader_id: int):
    logger.info(f"Начало перезагрузки трейдера {trader_id}")
    try:
        trader = Trader.objects.get(id=trader_id)
    except Trader.DoesNotExist:
        logger.error(f"Trader с id {trader_id} не существует.")
        return
    trader.reboot()
    logger.info(f"Завершена перезагрузка трейдера {trader_id}")
