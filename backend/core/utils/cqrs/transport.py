"""Транспортные модели для RPC over Redis Streams."""

import traceback
import uuid
from typing import Any

from pydantic import BaseModel

from core.utils.cqrs.base import Message, Registry, Result


class TransportRequest(BaseModel):
    """Обёртка сообщения для транспортного слоя."""

    request_id: str
    message_class_name: str
    payload: dict[str, Any]
    timeout: float = 30.0

    @classmethod
    def serialize(
        cls,
        message: Message,
        timeout: float = 30.0,
    ) -> "TransportRequest":
        """Message → TransportRequest."""
        return cls(
            request_id=uuid.uuid4().hex,
            message_class_name=type(message).__name__,
            payload=message.model_dump(),
            timeout=timeout,
        )

    def deserialize(self) -> Message | None:
        """TransportRequest → Message."""
        message_cls: type[Message] | None = Registry.get_message_class(
            message_class_name=self.message_class_name,
        )
        if message_cls is None:
            return None
        return message_cls.model_validate(obj=self.payload)


class TransportResponse(BaseModel):
    """Ответ транспортного слоя."""

    request_id: str
    message_class_name: str
    success: bool
    payload: dict[str, Any] | None = None
    error: str | None = None
    error_type: str | None = None
    error_traceback: str | None = None

    @classmethod
    def serialize(
        cls,
        request: TransportRequest,
        result: Result | None = None,
        exception: Exception | None = None,
    ) -> "TransportResponse":
        """Result/Exception → TransportResponse."""
        if exception is not None:
            return cls(
                request_id=request.request_id,
                message_class_name=request.message_class_name,
                success=False,
                error=str(exception),
                error_type=type(exception).__name__,
                error_traceback="".join(traceback.format_exception(exception)),
            )
        return cls(
            request_id=request.request_id,
            message_class_name=request.message_class_name,
            success=True,
            payload=result.model_dump() if result else None,
        )

    def deserialize(self) -> Result | None:
        """TransportResponse → Result."""
        if self.payload is None:
            return None
        result_cls: type[Result] | None = Registry.get_result_class(
            message_class_name=self.message_class_name,
        )
        if result_cls is None:
            return None
        return result_cls.model_validate(obj=self.payload)
