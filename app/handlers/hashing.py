"""Хеширование текста и файлов."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext

from .. import keyboards as kb
from .. import texts
from ..config import Settings
from ..keyboards import CB, HASH_ALGORITHMS
from ..services import hashing as hash_service
from ..states import HashSG
from ..utils import esc, human_size
from .helpers import edit_or_send

logger = logging.getLogger(__name__)
router = Router(name="hashing")


@router.callback_query(F.data == CB.HASH_MENU)
async def hash_menu(query: types.CallbackQuery, state: FSMContext) -> None:
    await query.answer()
    await state.set_state(HashSG.choose_algorithm)
    await edit_or_send(query, texts.HASH_CHOOSE_ALGORITHM, kb.hash_algorithms())


@router.callback_query(HashSG.choose_algorithm, F.data == CB.HASH_INFO)
async def hash_info(query: types.CallbackQuery, state: FSMContext) -> None:
    await query.answer()
    await state.set_state(HashSG.info)
    await edit_or_send(query, texts.HASH_INFO, kb.hash_back())


@router.callback_query(HashSG.choose_algorithm, F.data.startswith(CB.HASH_ALGO_PREFIX))
async def hash_choose_algorithm(
    query: types.CallbackQuery, state: FSMContext, settings: Settings
) -> None:
    await query.answer()
    algorithm = query.data.removeprefix(CB.HASH_ALGO_PREFIX)
    if algorithm not in HASH_ALGORITHMS:
        await query.answer(texts.STALE_BUTTON, show_alert=True)
        return

    await state.update_data(algorithm=algorithm)
    await state.set_state(HashSG.get_input)
    await edit_or_send(
        query,
        texts.HASH_ASK_INPUT.format(
            algorithm=HASH_ALGORITHMS[algorithm], max_mb=settings.max_file_size_mb
        ),
        kb.hash_back(),
    )


@router.message(HashSG.get_input)
async def hash_process_input(
    message: types.Message, state: FSMContext, bot: Bot, settings: Settings
) -> None:
    data = await state.get_data()
    algorithm = data.get("algorithm")
    if algorithm not in HASH_ALGORITHMS:
        await state.set_state(HashSG.choose_algorithm)
        await message.answer(texts.HASH_CHOOSE_ALGORITHM, reply_markup=kb.hash_algorithms())
        return

    label = HASH_ALGORITHMS[algorithm]
    progress = await message.answer(texts.HASH_CALCULATING.format(algorithm=label))

    try:
        if message.document:
            await _hash_document(message, progress, bot, algorithm, label, settings)
        elif message.text is not None:
            value, byte_len = await hash_service.hash_text(message.text, algorithm)
            await progress.edit_text(
                texts.HASH_RESULT_TEXT.format(
                    algorithm=label,
                    value=value,
                    length=f"{len(message.text):,}".replace(",", " "),
                    bytes_len=f"{byte_len:,}".replace(",", " "),
                ),
                reply_markup=kb.hash_back(),
            )
        else:
            await progress.edit_text(texts.HASH_UNSUPPORTED_INPUT, reply_markup=kb.hash_back())
    except Exception as exc:
        logger.exception("Ошибка хеширования")
        await _safe_edit(progress, texts.HASH_FILE_ERROR.format(error=esc(str(exc)[:200])))


async def _hash_document(
    message: types.Message,
    progress: types.Message,
    bot: Bot,
    algorithm: str,
    label: str,
    settings: Settings,
) -> None:
    document = message.document
    limit = settings.max_file_size_bytes

    if document.file_size and document.file_size > limit:
        await progress.edit_text(
            texts.HASH_FILE_TOO_BIG.format(
                size=human_size(document.file_size), max_mb=settings.max_file_size_mb
            ),
            reply_markup=kb.hash_back(),
        )
        return

    try:
        file_info = await bot.get_file(document.file_id)
    except TelegramBadRequest as exc:
        message_text = str(exc).lower()
        if "too big" in message_text:
            await progress.edit_text(
                texts.HASH_FILE_TOO_BIG.format(
                    size=human_size(document.file_size or 0), max_mb=settings.max_file_size_mb
                ),
                reply_markup=kb.hash_back(),
            )
        else:
            await progress.edit_text(texts.HASH_FILE_EXPIRED, reply_markup=kb.hash_back())
        return

    if not file_info.file_path:
        await progress.edit_text(texts.HASH_FILE_EXPIRED, reply_markup=kb.hash_back())
        return

    if file_info.file_size and file_info.file_size > limit:
        await progress.edit_text(
            texts.HASH_FILE_TOO_BIG.format(
                size=human_size(file_info.file_size), max_mb=settings.max_file_size_mb
            ),
            reply_markup=kb.hash_back(),
        )
        return

    stream = await bot.download_file(file_info.file_path)
    if stream is None:
        await progress.edit_text(texts.HASH_FILE_EXPIRED, reply_markup=kb.hash_back())
        return

    try:
        value = await hash_service.hash_stream(stream, algorithm)
        size = stream.getbuffer().nbytes if hasattr(stream, "getbuffer") else file_info.file_size
    finally:
        stream.close()

    filename = document.file_name or "file"
    await progress.edit_text(
        texts.HASH_RESULT_FILE.format(
            filename=esc(filename),
            algorithm=label,
            value=value,
            size=human_size(size or 0),
        ),
        reply_markup=kb.hash_back(),
    )


async def _safe_edit(message: types.Message, text: str) -> None:
    try:
        await message.edit_text(text, reply_markup=kb.hash_back())
    except Exception:
        logger.debug("Не удалось отредактировать сообщение с результатом")
