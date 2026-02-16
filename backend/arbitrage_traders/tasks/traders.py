import asyncio

from celery import shared_task
from loguru import logger

from arbitrage_traders.domain import ArbitrageTrader as DomainArbitrageTrader
from arbitrage_traders.models import ArbitrageTrader
from arbitrage_traders.schemas import ArbitrageTraderStatus
from exchange_clients.domain import AbstractExchangeClient as DomainExchangeClient
from exchange_clients.models import ExchangeClient
from exchanges.domain import ExchangeCandle as DomainExchangeCandle


@shared_task(queue="traders_process_for_exchange_client")
def arbitrage_traders_process_for_exchange_clients(
    left_exchange_client_id: int,
    right_exchange_client_id: int,
    traders_ids: list[int],
) -> None:
    """Обработка свечи для арбитражных трейдеров с двумя exchange_client."""

    left_client: ExchangeClient = ExchangeClient.active_objects.select_related(
        "exchange",
        "proxy",
    ).get(id=left_exchange_client_id)

    right_client: ExchangeClient = ExchangeClient.active_objects.select_related(
        "exchange",
        "proxy",
    ).get(id=right_exchange_client_id)

    traders = ArbitrageTrader.objects.select_related(
        "left_candle_source",
        "left_candle_source__trading_pair",
        "left_candle_source__exchange_client",
        "left_candle_source__exchange_client__exchange",
        "right_candle_source",
        "right_candle_source__trading_pair",
        "right_candle_source__exchange_client",
        "right_candle_source__exchange_client__exchange",
        "left_exchange_client",
        "left_exchange_client__exchange",
        "left_exchange_client__proxy",
        "right_exchange_client",
        "right_exchange_client__exchange",
        "right_exchange_client__proxy",
        "strategy",
        "risk_manager",
    ).filter(
        id__in=traders_ids,
        status__in=[
            ArbitrageTraderStatus.ENABLED,
            ArbitrageTraderStatus.PAUSED,
            ArbitrageTraderStatus.ERROR,
        ],
    )

    domain_left_client = left_client.instantiate()
    domain_right_client = right_client.instantiate()
    domain_traders: dict[ArbitrageTrader, DomainArbitrageTrader] = {}

    # Собираем свечи для каждого трейдера (последние 2 с каждой стороны)
    candles_by_trader: dict[int, tuple[list, list]] = {}
    for trader in traders:
        left_candles = trader.left_candle_source.get_last_candles(count=2)
        right_candles = trader.right_candle_source.get_last_candles(count=2)
        candles_by_trader[trader.pk] = (list(left_candles), list(right_candles))

    tasks = []
    for trader in traders:
        domain_trader = trader.instantiate(
            domain_left_exchange_client=domain_left_client,
            domain_right_exchange_client=domain_right_client,
        )
        trader.load(trader=domain_trader)
        domain_traders[trader] = domain_trader

        left_candles_list, right_candles_list = candles_by_trader.get(
            trader.pk, ([], [])
        )
        left_padded = [*left_candles_list, None, None]
        right_padded = [*right_candles_list, None, None]
        current_left, previous_left = left_padded[0], left_padded[1]
        current_right, previous_right = right_padded[0], right_padded[1]

        if previous_left and trader.has_existing_signal(left_candle=previous_left):
            tasks.append(
                _arbitrage_trader_check_opened_positions_async(
                    trader=domain_trader,
                    left_candle=current_left,  # type: ignore[arg-type]
                    right_candle=current_right,  # type: ignore[arg-type]
                )
            )
        else:
            tasks.append(
                _arbitrage_trader_handle_candle_async(
                    trader=domain_trader,
                    left_candle=previous_left,  # type: ignore[arg-type]
                    right_candle=previous_right,  # type: ignore[arg-type]
                )
            )

    if tasks:
        asyncio.run(
            _run_tasks_with_exchange_clients(
                left_exchange_client=domain_left_client,
                right_exchange_client=domain_right_client,
                tasks=tasks,
            )
        )

    for trader, domain_trader in domain_traders.items():
        trader.sync(trader=domain_trader)


async def _arbitrage_trader_check_opened_positions_async(
    trader: DomainArbitrageTrader,
    left_candle: DomainExchangeCandle | None,
    right_candle: DomainExchangeCandle | None,
):
    if left_candle is None or right_candle is None:
        logger.warning(f"Не удалось получить свечи для арбитражного трейдера {trader}.")
        return
    await trader.check_opened_positions(
        left_candle=left_candle,
        right_candle=right_candle,
    )


async def _arbitrage_trader_handle_candle_async(
    trader: DomainArbitrageTrader,
    left_candle: DomainExchangeCandle | None,
    right_candle: DomainExchangeCandle | None,
):
    if left_candle is None or right_candle is None:
        logger.warning(f"Не удалось получить свечи для арбитражного трейдера {trader}.")
        return
    await trader.handle_candle(
        left_candle=left_candle,
        right_candle=right_candle,
    )


async def _run_tasks_with_exchange_clients(
    left_exchange_client: DomainExchangeClient,
    right_exchange_client: DomainExchangeClient,
    tasks: list,
):
    async with left_exchange_client, right_exchange_client:
        await asyncio.gather(*tasks)


@shared_task(queue="trader_reboot")
def arbitrage_trader_reboot(trader_id: int):
    """
    Перезагружает арбитражного трейдера с историческими данными.
    """
    trader = ArbitrageTrader.objects.select_related(
        "left_candle_source",
        "left_candle_source__trading_pair",
        "left_candle_source__exchange_client",
        "left_candle_source__exchange_client__exchange",
        "right_candle_source",
        "right_candle_source__trading_pair",
        "right_candle_source__exchange_client",
        "right_candle_source__exchange_client__exchange",
        "left_exchange_client",
        "left_exchange_client__exchange",
        "left_exchange_client__proxy",
        "right_exchange_client",
        "right_exchange_client__exchange",
        "right_exchange_client__proxy",
        "strategy",
        "risk_manager",
    ).get(id=trader_id)
    trader.reboot()
