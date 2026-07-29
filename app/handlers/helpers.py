"""Вспомогательные функции для хендлеров."""

from __future__ import annotations

import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

logger = logging.getLogger(__name__)


async def edit_or_send(
    query: CallbackQuery,
    text: str,
    keyboard: InlineKeyboardMarkup | None = None,
) -> None:
    """Редактирует сообщение, а если нельзя — присылает новое."""
    message = query.message
    if message is None:
        return
    try:
        await message.edit_text(text, reply_markup=keyboard)
        return
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            return
        logger.debug("edit_text не удался (%s), отправляю новое сообщение", exc)
    except Exception as exc:
        logger.debug("edit_text не удался (%s), отправляю новое сообщение", exc)

    try:
        await message.answer(text, reply_markup=keyboard)
    except Exception:
        logger.exception("Не удалось отправить сообщение")


async def safe_delete(message: Message | None) -> None:
    """Удаление без исключений: прав может не быть, сообщение может устареть."""
    if message is None:
        return
    try:
        await message.delete()
    except Exception:
        pass


async def delete_by_id(bot, chat_id: int, message_id: int | None) -> None:
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass
