"""
Тесты для Celery задач Telegram ботов с проверкой SQL-запросов.
"""

from unittest.mock import patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from telegram_bots.models import TelegramBot, TelegramChat
from telegram_bots.tasks import send_notification


@pytest.mark.django_db
class TestSendNotification:
    """Тесты для задачи send_notification."""

    def test_send_notification_no_active_bot(self, db):
        """Тест когда нет активного бота."""
        # Arrange: создаем неактивного бота
        TelegramBot.objects.create(
            name="Test Bot",
            token="test_token",
            is_active=False,
        )

        # Act & Assert: проверяем количество запросов
        with CaptureQueriesContext(connection) as queries:
            send_notification(message="Test message")

        # Ожидаем: 1 запрос для поиска активного бота
        assert len(queries) == 1

    def test_send_notification_no_chats(self, db):
        """Тест когда нет чатов для отправки."""
        # Arrange: создаем активного бота без чатов
        TelegramBot.objects.create(
            name="Test Bot",
            token="test_token",
            is_active=True,
        )

        # Act & Assert: проверяем количество запросов
        with CaptureQueriesContext(connection) as queries:
            send_notification(message="Test message")

        # Ожидаем:
        # 1. Запрос для получения активного бота
        # 2. Запрос для проверки чатов
        assert len(queries) == 2

    @patch("telegram_bots.tasks.asyncio.run")
    def test_send_notification_success(self, mock_asyncio_run, db):
        """Тест успешной отправки уведомления."""
        # Arrange: создаем бота и чаты
        bot = TelegramBot.objects.create(
            name="Test Bot",
            token="test_token_123",
            is_active=True,
        )
        TelegramChat.objects.create(
            bot=bot,
            chat_id="12345",
            name="Chat 1",
            is_active=True,
        )
        TelegramChat.objects.create(
            bot=bot,
            chat_id="67890",
            name="Chat 2",
            is_active=True,
        )

        # Act & Assert: проверяем количество запросов
        with CaptureQueriesContext(connection) as queries:
            send_notification(message="Test notification")

        # Ожидаем:
        # 1. Запрос для получения активного бота
        # 2. Запрос exists() для чатов
        # 3. Запрос для получения списка чатов
        assert len(queries) == 3

        # Проверяем вызов async_send_notification
        mock_asyncio_run.assert_called_once()

    @patch("telegram_bots.tasks.asyncio.run")
    def test_send_notification_query_count_with_multiple_chats(
        self, mock_asyncio_run, db
    ):
        """Тест количества запросов с несколькими чатами."""
        # Arrange: создаем бота и 5 чатов
        bot = TelegramBot.objects.create(
            name="Test Bot",
            token="test_token",
            is_active=True,
        )
        for i in range(5):
            TelegramChat.objects.create(
                bot=bot,
                chat_id=f"chat_{i}",
                name=f"Chat {i}",
                is_active=True,
            )

        # Act & Assert
        with CaptureQueriesContext(connection) as queries:
            send_notification(message="Bulk test")

        # Количество запросов НЕ должно зависеть от количества чатов
        # Ожидаем те же 3 запроса
        assert len(queries) == 3

    @patch("telegram_bots.tasks.asyncio.run")
    def test_send_notification_filters_inactive_chats(self, mock_asyncio_run, db):
        """Тест фильтрации неактивных чатов."""
        # Arrange: создаем бота с активными и неактивными чатами
        bot = TelegramBot.objects.create(
            name="Test Bot",
            token="test_token",
            is_active=True,
        )
        TelegramChat.objects.create(
            bot=bot,
            chat_id="active_chat",
            name="Active",
            is_active=True,
        )
        TelegramChat.objects.create(
            bot=bot,
            chat_id="inactive_chat",
            name="Inactive",
            is_active=False,  # Неактивный чат
        )

        # Act
        with CaptureQueriesContext(connection) as queries:
            send_notification(message="Test")

        # Assert: должны быть те же 3 запроса
        assert len(queries) == 3
