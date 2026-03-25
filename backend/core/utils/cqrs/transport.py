"""Транспортные модели для Command/Query Pattern."""

import uuid
from typing import Any

from pydantic import BaseModel, TypeAdapter

from core.utils.cqrs.commands import BaseMessage


class TransportRequest(BaseModel):
    """Обёртка сообщения для транспортного слоя."""

    request_id: str
    message_class: str
    payload: dict[str, Any]

    @classmethod
    def from_message(cls, message: BaseMessage[Any]) -> "TransportRequest":
        return cls(
            request_id=uuid.uuid4().hex,
            message_class=type(message).__name__,
            payload=message.model_dump(),
        )

    def resolve_message(
        self,
    ) -> BaseMessage[Any] | None:
        """Восстанавливает команду/запрос из payload."""
        cls = BaseMessage.resolve(self.message_class)
        if cls is None:
            return None
        return cls.model_validate(self.payload)


class TransportResponse(BaseModel):
    """Ответ транспортного слоя."""

    request_id: str
    message_class: str
    success: bool
    payload: dict | list | None = None
    error: str | None = None
    error_type: str | None = None

    def parse_result(self, adapter: TypeAdapter[Any] | None) -> Any:
        """Десериализует data в типизированный результат."""
        if self.payload is None or adapter is None:
            return self.payload
        return adapter.validate_python(self.payload)


class TransportResponseBuilder:
    """Фабрика для создания TransportResponse."""

    @staticmethod
    def make_success(
        request: TransportRequest,
        result: Any,
        adapter: TypeAdapter[Any] | None,
    ) -> TransportResponse:
        if result is None or adapter is None:
            payload = result
        else:
            payload = adapter.dump_python(result, mode="json")
        return TransportResponse(
            request_id=request.request_id,
            message_class=request.message_class,
            success=True,
            payload=payload,
        )

    @staticmethod
    def make_error(
        request: TransportRequest,
        exception: Exception,
    ) -> TransportResponse:
        return TransportResponse(
            request_id=request.request_id,
            message_class=request.message_class,
            success=False,
            error=str(exception),
            error_type=type(exception).__name__,
        )
