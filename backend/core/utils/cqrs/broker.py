"""Абстрактный брокер для Command/Query Pattern."""

from abc import ABC, abstractmethod

from core.utils.cqrs.transport import TransportRequest, TransportResponse


class BusBroker(ABC):
    """Абстрактный брокер для шины команд/запросов."""

    # --- Subscriptions ---

    @abstractmethod
    def subscribe(self, stream: str, group: str) -> None:
        """Подписывается на стрим с указанной consumer group."""

    # --- Consumer operations ---

    @abstractmethod
    async def read(self, timeout: int = 1) -> tuple[str, TransportRequest] | None:
        """Читает сообщение из подписанных стримов."""

    @abstractmethod
    async def reply(
        self,
        message_id: str,
        response: TransportResponse,
    ) -> None:
        """Отправляет ответ и подтверждает обработку."""

    # --- Producer operations ---

    @abstractmethod
    async def send(self, request: TransportRequest) -> None:
        """Отправляет сообщение в стрим команды."""

    @abstractmethod
    async def wait_reply(
        self, request_id: str, timeout: float = 30.0
    ) -> TransportResponse:
        """Ждёт ответ."""

    # --- Lifecycle ---

    @abstractmethod
    async def create_consumer_group(self) -> None:
        """Создаёт consumer group для подписок."""

    @abstractmethod
    async def close(self) -> None:
        """Закрывает соединение."""
