import asyncio
import contextlib
from collections.abc import Coroutine

from exchange_clients.domain import AbstractExchangeClient as DomainExchangeClient


async def run_with_exchange_client(
    exchange_client: DomainExchangeClient,
    tasks: list[Coroutine],
) -> list:
    """Выполняет корутины внутри контекста одного exchange_client."""
    async with exchange_client:
        return await asyncio.gather(*tasks)


async def run_with_exchange_clients(
    exchange_clients: list[DomainExchangeClient],
    tasks: list[Coroutine],
) -> list:
    """Выполняет корутины внутри контекста нескольких exchange_client."""
    async with contextlib.AsyncExitStack() as stack:
        for client in exchange_clients:
            await stack.enter_async_context(client)
        return await asyncio.gather(*tasks)
