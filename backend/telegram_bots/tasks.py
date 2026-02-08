import asyncio

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from celery import shared_task
from django.db import models

from telegram_bots.models import TelegramBot, TelegramChat


async def async_send_notification(
    token: str, chat_ids: list[str], message: str
) -> None:
    async with Bot(token=token) as bot:
        for chat_id in chat_ids:
            try:
                await bot.send_message(chat_id=chat_id, text=message)
                await asyncio.sleep(0.1)
            except TelegramRetryAfter as e:
                print(f"Flood control: Ждем {e.retry_after} сек для {chat_id}")
                await asyncio.sleep(e.retry_after)
                await bot.send_message(chat_id=chat_id, text=message)
            except (TelegramBadRequest, TelegramNetworkError) as e:
                print(f"Ошибка отправки в {chat_id}: {e}")
            except Exception as e:
                print(f"Неизвестная ошибка в {chat_id}: {e}")


@shared_task()
def send_notification(message: str) -> None:
    """
    Отправляет уведомление в Telegram через активного бота во все связанные чаты.
    """
    active_bot: TelegramBot = TelegramBot.active_objects.first()
    if not active_bot:
        print("Нет активного Telegram бота для отправки уведомления.")
        return

    token = active_bot.token
    chats: models.QuerySet[TelegramChat] = TelegramChat.active_objects.filter(
        bot=active_bot
    )
    if not chats.exists():
        print("Нет чатов для отправки уведомления.")
        return

    asyncio.run(
        async_send_notification(
            token=token, chat_ids=[chat.chat_id for chat in chats], message=message
        )
    )
