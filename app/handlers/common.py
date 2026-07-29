"""Старт, справка, навигация и «ловцы» неожиданного ввода."""

from __future__ import annotations

import logging

from aiogram import F, Router, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext

from .. import keyboards as kb
from .. import texts
from ..config import Settings
from ..keyboards import CB
from ..states import MainSG
from .helpers import edit_or_send

logger = logging.getLogger(__name__)

priority_router = Router(name="common-priority")
fallback_router = Router(name="common-fallback")


@priority_router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(MainSG.menu)
    await message.answer(texts.MAIN_MENU, reply_markup=kb.main_menu())


@priority_router.message(Command("help"))
async def cmd_help(message: types.Message, state: FSMContext, settings: Settings) -> None:
    await state.clear()
    await state.set_state(MainSG.menu)
    await message.answer(
        texts.HELP.format(
            max_mb=settings.max_file_size_mb,
            x509_bits=settings.rsa_x509_key_size,
        ),
        reply_markup=kb.main_menu(),
    )


@priority_router.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(MainSG.menu)
    await message.answer(texts.CANCELLED, reply_markup=kb.main_menu())


@priority_router.callback_query(F.data.in_({CB.MAIN_MENU, CB.CANCEL}))
async def nav_main_menu(query: types.CallbackQuery, state: FSMContext) -> None:
    """Единая точка возврата в главное меню."""
    await query.answer()
    await state.clear()
    await state.set_state(MainSG.menu)
    await edit_or_send(query, texts.MAIN_MENU, kb.main_menu())


@fallback_router.callback_query()
async def unknown_callback(query: types.CallbackQuery, state: FSMContext) -> None:
    """Кнопка из устаревшего сообщения либо из чужого состояния."""
    logger.debug("Не обработан callback %r в состоянии %s", query.data, await state.get_state())
    await query.answer(texts.STALE_BUTTON, show_alert=True)
    await state.clear()
    await state.set_state(MainSG.menu)
    await edit_or_send(query, texts.MAIN_MENU, kb.main_menu())


@fallback_router.message()
async def unknown_message(message: types.Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await state.set_state(MainSG.menu)
    await message.answer(texts.UNKNOWN_INPUT, reply_markup=kb.main_menu())
