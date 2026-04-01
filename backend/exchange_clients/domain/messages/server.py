"""RPCServer с инжекцией exchange client из пула."""

from core.utils.cqrs import Handler, Message, RPCServer
from exchange_clients.domain.pool import ExchangeClientPool

from .messages import ExchangeClientMessage


class ExchangeClientRPCServer(RPCServer):
    """RPCServer, который инжектирует exchange client в хендлер."""

    def __init__(self, broker, pool: ExchangeClientPool) -> None:
        super().__init__(broker=broker)
        self._pool = pool

    def _create_handler(self, handler_cls: type, message: Message) -> Handler:
        if not isinstance(message, ExchangeClientMessage):
            raise TypeError(
                f"Ожидается ExchangeClientMessage, получен {type(message).__name__}"
            )
        client = self._pool.get(client_id=message.exchange_client_id)
        if client is None:
            raise RuntimeError(
                f"Нет соединения для exchange_client_id={message.exchange_client_id}"
            )
        return handler_cls(client=client)
