"""Абстрактные хендлеры для Command/Query Pattern."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class CommandHandler(ABC):
    """Хендлер команды. Получает контекст через конструктор."""

    @abstractmethod
    async def handle(self, command: Any) -> Any:
        raise NotImplementedError


class QueryHandler(ABC):
    """Хендлер запроса. Stateless — без контекста."""

    @abstractmethod
    async def handle(self, query: Any) -> Any:
        raise NotImplementedError
