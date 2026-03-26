"""Bus для exchange client."""

from core.bus import create_redis_broker
from core.utils.cqrs import BusWorker, Handler, Message
from exchange_clients.domain.pool import ExchangeClientPool

from .handlers import *  # noqa: F403
from .messages import ExchangeClientMessage


class ExchangeClientWorker(BusWorker):
    """Worker для exchange client.

    Переопределяет _create_handler() — получает client из pool
    и передаёт в конструктор хендлера.
    """

    def __init__(self, pool: ExchangeClientPool) -> None:
        super().__init__(broker=create_redis_broker())
        self._pool: ExchangeClientPool = pool
        self.add_background_task(task=pool.sync_loop(self.shutdown_event))
        self.add_on_shutdown(task=pool.close())

    def _create_handler(self, handler_cls: type, message: Message) -> Handler:
        """Инжектирует exchange client в хендлер."""
        if not isinstance(message, ExchangeClientMessage):
            raise TypeError(
                f"Ожидается ExchangeClientMessage, получен {type(message).__name__}"
            )
        client = self._pool.get_client(
            client_id=message.exchange_client_id,
        )
        if client is None:
            raise RuntimeError(
                f"Нет соединения для exchange_client_id={message.exchange_client_id}"
            )
        return handler_cls(client=client)
