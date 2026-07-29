"""Middleware-слой: приватные чаты, список доступа, антифлуд."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User

from . import texts
from .config import Settings

logger = logging.getLogger(__name__)


class PrivateChatOnlyMiddleware(BaseMiddleware):
    """Пропускаем только личные сообщения."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        chat = data.get("event_chat")
        if chat is not None and chat.type != "private":
            if isinstance(event, Message):
                try:
                    await event.answer(texts.PRIVATE_ONLY)
                except Exception:
                    pass
            return None
        return await handler(event, data)


class AccessMiddleware(BaseMiddleware):
    """Белый список пользователей (если задан ALLOWED_USER_IDS)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not self.settings.access_is_restricted:
            return await handler(event, data)

        user: User | None = data.get("event_from_user")
        if user is None or user.id not in self.settings.allowed_user_ids:
            uid = user.id if user else "?"
            logger.warning("Отклонён доступ для пользователя %s", uid)
            text = texts.ACCESS_DENIED.format(user_id=uid)
            if isinstance(event, Message):
                await event.answer(text)
            elif isinstance(event, CallbackQuery):
                await event.answer("Доступ закрыт", show_alert=True)
            return None
        return await handler(event, data)


class ThrottlingMiddleware(BaseMiddleware):
    """Простой антифлуд: не чаще одного апдейта в N секунд на пользователя."""

    def __init__(self, rate: float) -> None:
        self.rate = rate
        self._last: dict[int, float] = defaultdict(float)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None or self.rate <= 0:
            return await handler(event, data)

        now = time.monotonic()
        if now - self._last[user.id] < self.rate:
            if isinstance(event, CallbackQuery):
                await event.answer(texts.RATE_LIMITED)
            return None
        self._last[user.id] = now

        if len(self._last) > 10_000:
            cutoff = now - 3600
            for uid in [k for k, v in self._last.items() if v < cutoff]:
                self._last.pop(uid, None)

        return await handler(event, data)


class HeavyOperationLimiter:
    """Отдельный кулдаун на дорогие операции (генерация RSA)."""

    def __init__(self, cooldown: int) -> None:
        self.cooldown = cooldown
        self._last: dict[int, float] = {}

    def check(self, user_id: int) -> int:
        """Возвращает 0, если можно, иначе — сколько секунд ждать."""
        now = time.monotonic()
        last = self._last.get(user_id, 0.0)
        remaining = self.cooldown - (now - last)
        if remaining > 0:
            return int(remaining) + 1
        return 0

    def mark(self, user_id: int) -> None:
        self._last[user_id] = time.monotonic()
