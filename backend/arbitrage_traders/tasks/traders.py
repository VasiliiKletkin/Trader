import asyncio

from celery import shared_task

from arbitrage_traders.domain import ArbitrageCandle as DomainArbitrageCandle
from arbitrage_traders.domain import ArbitrageTrader as DomainArbitrageTrader
from arbitrage_traders.models import ArbitrageTrader
from arbitrage_traders.schemas import ArbitrageTraderStatus
from exchange_clients.domain import AbstractExchangeClient as DomainExchangeClient
from exchange_clients.models import ExchangeClient


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

    tasks = []
    for trader in traders:
        domain_trader = trader.instantiate(
            domain_left_exchange_client=domain_left_client,
            domain_right_exchange_client=domain_right_client,
        )
        domain_traders[trader] = domain_trader
        trader.load(trader=domain_trader)
        left_candles, right_candles = trader.get_last_candles(count=1)
        if left_candles and right_candles:
            candle = DomainArbitrageCandle(
                left=left_candles[0].instantiate(),
                right=right_candles[0].instantiate(),
            )
            tasks.append(
                _arbitrage_trader_handle_candle_async(
                    trader=domain_trader,
                    candle=candle,
                )
            )

    asyncio.run(
        _run_tasks_with_exchange_clients(
            left_exchange_client=domain_left_client,
            right_exchange_client=domain_right_client,
            tasks=tasks,
        )
    )

    for trader, domain_trader in domain_traders.items():
        trader.sync(trader=domain_trader)


async def _arbitrage_trader_handle_candle_async(
    trader: DomainArbitrageTrader,
    candle: DomainArbitrageCandle,
):
    await trader.handle_candle(candle=candle)


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
