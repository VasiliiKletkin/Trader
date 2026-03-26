"""Базовые классы для RPC over Redis Streams."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel


class BusError(Exception):
    """Базовая ошибка шины."""


class BusTimeoutError(BusError):
    """Worker не ответил в указанный timeout."""


class BusConnectionError(BusError):
    """Соединение с Redis потеряно."""


class BusHandlerError(BusError):
    """Handler вернул ошибку."""

    def __init__(self, message: str, error_type: str | None = None) -> None:
        self.error_type: str | None = error_type
        super().__init__(message)


class Result(BaseModel):
    """Базовый класс результата хендлера."""


class Message(BaseModel):
    """Базовый класс сообщения."""


class Handler(ABC):
    """Базовый хендлер сообщения.

    Регистрируется через декоратор @Registry.handler.

    Пример::

        @Registry.handler(FetchBalancesMessage, FetchBalancesResult)
        class FetchBalancesHandler(Handler):
            async def handle(self, message: FetchBalancesMessage) -> FetchBalancesResult:
                ...
    """

    @abstractmethod
    async def handle(self, message: Any) -> Result | None:
        raise NotImplementedError


class Registry:
    """Реестр: message_class_name → (MessageClass, HandlerClass, ResultClass)."""

    # {message_class_name: (MessageClass, HandlerClass, ResultClass | None)}
    _registry: ClassVar[dict[str, tuple[type[Message], type, type[Result] | None]]] = {}

    @classmethod
    def handler(
        cls,
        message_cls: type[Message],
        result_cls: type[Result] | None = None,
    ):
        """Декоратор для регистрации хендлера.

        Пример::

            @Registry.handler(FetchBalancesMessage, FetchBalancesResult)
            class FetchBalancesHandler(ExchangeClientHandler):
                async def handle(self, message):
                    ...
        """

        def decorator(handler_cls: type) -> type:
            cls._registry[message_cls.__name__] = (
                message_cls,
                handler_cls,
                result_cls,
            )
            return handler_cls

        return decorator

    @classmethod
    def get_message_class(
        cls,
        message_class_name: str,
    ) -> type[Message] | None:
        """message_class_name → MessageClass."""
        entry = cls._registry.get(message_class_name)
        return entry[0] if entry else None

    @classmethod
    def get_handler_class(
        cls,
        message_class_name: str,
    ) -> type | None:
        """message_class_name → HandlerClass."""
        entry = cls._registry.get(message_class_name)
        return entry[1] if entry else None

    @classmethod
    def get_result_class(
        cls,
        message_class_name: str,
    ) -> type[Result] | None:
        """message_class_name → ResultClass."""
        entry = cls._registry.get(message_class_name)
        return entry[2] if entry else None

    @classmethod
    def get_registered_handlers(cls) -> dict[str, type]:
        """Возвращает {message_class_name: handler_cls}."""
        return {name: entry[1] for name, entry in cls._registry.items()}
