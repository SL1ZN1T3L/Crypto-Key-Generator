"""Сборка роутеров."""

from aiogram import Dispatcher

from . import common, hashing, ssh, x509


def register_handlers(dp: Dispatcher) -> None:
    dp.include_router(common.priority_router)
    dp.include_router(ssh.router)
    dp.include_router(hashing.router)
    dp.include_router(x509.router)
    dp.include_router(common.fallback_router)
