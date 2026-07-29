"""Точка входа: python -m app"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import sys

from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage

from .config import ConfigError, Settings, load_settings
from .handlers import register_handlers
from .health import heartbeat_loop
from .logging_setup import setup_logging
from .handlers import ssh as ssh_handlers
from .middlewares import AccessMiddleware, PrivateChatOnlyMiddleware, ThrottlingMiddleware
from .services.quota import SshQuota
from .services.quota_backend import MemoryBackend, RedisBackend

logger = logging.getLogger("crypto-bot")

COMMANDS = [
    types.BotCommand(command="start", description="Главное меню"),
    types.BotCommand(command="help", description="Справка по функциям"),
    types.BotCommand(command="cancel", description="Отменить текущую операцию"),
]


def build_storage_and_backend(settings: Settings):
    """Возвращает (storage для FSM, backend для квот, redis-клиент либо None)."""
    if not settings.redis_url:
        return MemoryStorage(), MemoryBackend(), None

    try:
        from redis.asyncio import Redis
        from aiogram.fsm.storage.redis import RedisStorage
    except ImportError as exc:
        raise ConfigError(
            "REDIS_URL задан, но пакет redis не установлен.\n"
            "  pip install 'redis>=5' — либо уберите REDIS_URL"
        ) from exc

    client = Redis.from_url(settings.redis_url, decode_responses=True)
    storage = RedisStorage(redis=Redis.from_url(settings.redis_url))
    return storage, RedisBackend(client), client


def build_dispatcher(settings: Settings, storage: BaseStorage | None = None,
                     backend=None) -> Dispatcher:
    dp = Dispatcher(storage=storage or MemoryStorage())

    for observer in (dp.message, dp.callback_query):
        observer.middleware(PrivateChatOnlyMiddleware())
        observer.middleware(AccessMiddleware(settings))
        observer.middleware(ThrottlingMiddleware(settings.rate_limit_seconds))

    register_handlers(dp)

    quota = SshQuota(settings.build_quota_config(), backend=backend)
    ssh_handlers.configure_concurrency(settings.max_concurrent_ssh)
    dp["quota"] = quota
    dp["settings"] = settings
    return dp


async def run() -> None:
    settings = load_settings()
    setup_logging(settings)

    logger.info("Запуск крипто-бота")
    if settings.access_is_restricted:
        logger.info("Доступ ограничен списком из %d пользователей", len(settings.allowed_user_ids))
    else:
        logger.warning(
            "ALLOWED_USER_IDS не задан: ботом может пользоваться кто угодно. "
            "Экспорт ключей позволяет подключаться по SSH к произвольным хостам "
            "с IP этого сервера — задайте список ID или SSH_EXPORT_ENABLED=0."
        )
    if not settings.ssh_export_enabled:
        logger.info("Экспорт ключей на серверы отключён")

    storage, backend, redis_client = build_storage_and_backend(settings)
    if redis_client is not None:
        try:
            await redis_client.ping()
            logger.info("Redis подключён: квоты и состояния переживут рестарт")
        except Exception as exc:
            raise ConfigError(f"Redis по адресу REDIS_URL недоступен: {exc}") from exc
    else:
        logger.warning(
            "REDIS_URL не задан: счётчики квот хранятся в памяти и "
            "обнуляются при рестарте контейнера."
        )

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = build_dispatcher(settings, storage=storage, backend=backend)

    heartbeat = asyncio.create_task(
        heartbeat_loop(settings.healthcheck_file, settings.heartbeat_interval)
    )

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    async def _wait_for_stop() -> None:
        await stop_event.wait()
        logger.info("Получен сигнал остановки, завершаю polling")
        await dp.stop_polling()

    stopper = asyncio.create_task(_wait_for_stop())

    try:
        await bot.set_my_commands(COMMANDS)
    except Exception as exc:
        logger.warning("Не удалось зарегистрировать команды: %s", exc)

    try:
        await dp.start_polling(bot, drop_pending_updates=True)
    finally:
        for task in (heartbeat, stopper):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await bot.session.close()
        if redis_client is not None:
            await redis_client.aclose()
        await storage.close()
        settings.healthcheck_file.unlink(missing_ok=True)
        logger.info("Бот остановлен")


def main() -> None:
    try:
        asyncio.run(run())
    except ConfigError as exc:
        print(f"Ошибка конфигурации:\n{exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
