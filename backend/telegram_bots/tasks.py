import asyncio
from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from celery import shared_task

from telegram_bots.models import TelegramBot, TelegramChat


@shared_task(queue="send_notifications")
def send_notification(message: str) -> None:
    """
    Отправляет уведомление в Telegram через активного бота во все связанные чаты.
    """
    active_bot: TelegramBot = TelegramBot.active_objects.first()
    if not active_bot:
        print("Нет активного Telegram бота для отправки уведомления.")
        return

    token = active_bot.token
    chats = TelegramChat.active_objects.filter(bot=active_bot)
    if not chats.exists():
        print("Нет чатов для отправки уведомления.")
        return

    async def send_notification(token: str, chat_ids: list[str], message: str) -> None:
        bot = Bot(token=token)
        for chat_id in chat_ids:
            try:
                await bot.send_message(chat_id=chat_id, text=message)
            except TelegramRetryAfter as e:
                print(
                    f"Flood control: Повтор через {e.retry_after} сек для чата {chat_id}"
                )
                await asyncio.sleep(e.retry_after)
                await bot.send_message(chat_id=chat_id, text=message)
            except TelegramBadRequest as e:
                print(f"Ошибка при отправке сообщения в чат {chat_id}: {e}")
            except TelegramNetworkError as e:
                print(f"Сетевая ошибка при отправке сообщения в чат {chat_id}: {e}")
            except Exception as e:
                print(f"Неизвестная ошибка при отправке в чат {chat_id}: {e}")

    asyncio.run(
        send_notification(
            token=token, chat_ids=[chat.chat_id for chat in chats], message=message
        )
    )
