"""Async-генераторы над Django ORM через sync_to_async.

Назначение: потоковое чтение большого числа ORM-объектов из async-контекста
без материализации всего набора в память и без DJANGO_ALLOW_ASYNC_UNSAFE.

Основной сценарий — backtest/оптимизация, где свечи читаются лениво через
`QuerySet.iterator()` и передаются в `DomainTrader.reboot(candle_iterator)`.
"""

from collections.abc import AsyncIterator, Iterable
from itertools import islice

from asgiref.sync import sync_to_async


async def aiter_sync_chunked[T](
    iterable: Iterable[T],
    chunk_size: int = 1000,
) -> AsyncIterator[T]:
    """Async-итерация над sync-iterable батчами через sync_to_async.

    Вызов `iter(iterable)` и последующие `next()` выполняются в
    sync-thread через `sync_to_async`, поэтому можно передавать ленивый
    Django QuerySet или generator, дёргающий ORM — SQL-запросы пойдут в
    sync-контексте.

    Для конвертации ORM → domain используйте generator expression на
    входе: `aiter_sync_chunked(x.instantiate() for x in queryset)`.
    """

    @sync_to_async(thread_sensitive=True)
    def _get_iter():
        return iter(iterable)

    sync_iter = await _get_iter()

    @sync_to_async(thread_sensitive=True)
    def _fetch_chunk():
        return list(islice(sync_iter, chunk_size))

    while True:
        chunk = await _fetch_chunk()
        if not chunk:
            return
        for item in chunk:
            yield item


async def aiter_from_iterable[T](iterable: Iterable[T]) -> AsyncIterator[T]:
    """Async-обёртка над готовым sync-iterable.

    Не использует sync_to_async и не делает чанкинг — предназначена для уже
    материализованных коллекций (например, в тестах `reboot`/`optimize`).
    Для случаев с ленивым QuerySet используйте `aiter_sync_chunked`.
    """
    for item in iterable:
        yield item
