"""Транспортные модели для RPC over Redis Streams."""

import traceback
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from core.utils.rpc.base import Message, Registry, Result


class TransportRequest(BaseModel):
    """Обёртка сообщения для транспортного слоя."""

    request_id: str
    message_class_name: str
    payload: dict[str, Any]
    timestamp: datetime
    reply_timeout: int

    @classmethod
    def serialize(
        cls,
        message: Message,
        reply_timeout: int,
    ) -> "TransportRequest":
        """Message → TransportRequest."""
        return cls(
            request_id=uuid.uuid4().hex,
            message_class_name=type(message).__name__,
            payload=message.model_dump(),
            reply_timeout=reply_timeout,
            timestamp=datetime.now(UTC),
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
    timestamp: datetime
    payload: dict[str, Any] | None = None
    error_message: str | None = None
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
                error_message=str(exception),
                error_type=type(exception).__name__,
                error_traceback="".join(traceback.format_exception(exception)),
                timestamp=datetime.now(UTC),
            )
        return cls(
            request_id=request.request_id,
            message_class_name=request.message_class_name,
            success=True,
            payload=result.model_dump() if result else None,
            timestamp=datetime.now(UTC),
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
