"""Мастер X.509: самоподписанные сертификаты и CSR."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from aiogram import Bot, F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import BufferedInputFile

from .. import keyboards as kb
from .. import texts
from ..config import Settings
from ..keyboards import CB
from ..services import certificates as cert_service
from ..states import X509SG
from ..utils import esc, sanitize_filename
from .helpers import edit_or_send, safe_delete

logger = logging.getLogger(__name__)
router = Router(name="x509")


@dataclass(frozen=True)
class Step:
    state: State
    field: str
    prompt: str
    optional: bool
    next_state: State | None
    validator: Callable[[str], str | None] | None = None
    transform: Callable[[str], str] = str.strip


def _validate_country(value: str) -> str | None:
    return None if len(value) == 2 and value.isalpha() and value.isascii() else texts.X509_BAD_COUNTRY


def _validate_email(value: str) -> str | None:
    if "@" not in value:
        return texts.X509_BAD_EMAIL
    local, _, domain = value.rpartition("@")
    if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
        return texts.X509_BAD_EMAIL
    return None


_STEPS: tuple[Step, ...] = (
    Step(X509SG.common_name, "CN", texts.X509_ASK_COMMON_NAME, False, X509SG.organization),
    Step(X509SG.organization, "O", texts.X509_ASK_ORGANIZATION, True, X509SG.country),
    Step(X509SG.country, "C", texts.X509_ASK_COUNTRY, True, X509SG.state_province,
         _validate_country, lambda v: v.strip().upper()),
    Step(X509SG.state_province, "ST", texts.X509_ASK_STATE, True, X509SG.locality),
    Step(X509SG.locality, "L", texts.X509_ASK_LOCALITY, True, X509SG.email),
    Step(X509SG.email, "Email", texts.X509_ASK_EMAIL, True, None, _validate_email),
)

_BY_STATE = {step.state: step for step in _STEPS}
_OPTIONAL_STATES = [step.state for step in _STEPS if step.optional]


def _prompt_text(step: Step, kind: str = "") -> str:
    text = step.prompt.format(kind=kind) if "{kind}" in step.prompt else step.prompt
    return text + (texts.X509_OPTIONAL_HINT if step.optional else "")


def _keyboard(step: Step):
    return kb.x509_skip() if step.optional else kb.cancel_only()


@router.callback_query(F.data == CB.X509_MENU)
async def x509_menu(query: types.CallbackQuery, state: FSMContext) -> None:
    await query.answer()
    await state.set_state(X509SG.menu)
    await edit_or_send(query, texts.X509_MENU, kb.x509_menu())


@router.callback_query(X509SG.menu, F.data.in_({CB.X509_SELF_SIGNED, CB.X509_CSR}))
async def x509_start(query: types.CallbackQuery, state: FSMContext) -> None:
    await query.answer()
    is_csr = query.data == CB.X509_CSR
    await state.set_data({"is_csr": is_csr, "details": {}})
    await state.set_state(X509SG.common_name)
    kind = texts.KIND_CSR if is_csr else texts.KIND_CERT
    await edit_or_send(query, _prompt_text(_STEPS[0], kind), kb.cancel_only())


@router.callback_query(F.data == CB.X509_SKIP)
async def x509_skip(
    query: types.CallbackQuery, state: FSMContext, bot: Bot, settings: Settings
) -> None:
    """«Пропустить» работает на всех необязательных шагах."""
    current = await state.get_state()
    step = _BY_STATE.get(current)
    if step is None or not step.optional:
        await query.answer(texts.STALE_BUTTON, show_alert=True)
        return
    await query.answer()
    await _advance(step, query.message, state, bot, settings, edit=query)


def _make_text_handler(step: Step):
    async def handler(
        message: types.Message, state: FSMContext, bot: Bot, settings: Settings
    ) -> None:
        await _handle_text(step, message, state, bot, settings)

    handler.__name__ = f"x509_field_{step.field.lower()}"
    return handler


for _step in _STEPS:
    router.message(_step.state)(_make_text_handler(_step))


async def _handle_text(
    step: Step, message: types.Message, state: FSMContext, bot: Bot, settings: Settings
) -> None:
    raw = message.text or ""
    value = step.transform(raw)

    if not value:
        if not step.optional:
            await message.answer(texts.X509_EMPTY_CN, reply_markup=kb.cancel_only())
            return
        await _advance(step, message, state, bot, settings)
        return

    limit = cert_service.FIELD_LIMITS.get(step.field)
    if limit and len(value) > limit:
        await message.answer(
            texts.X509_TOO_LONG.format(limit=limit), reply_markup=_keyboard(step)
        )
        return

    if step.validator is not None:
        error = step.validator(value)
        if error:
            await message.answer(error, reply_markup=_keyboard(step))
            return

    data = await state.get_data()
    details = dict(data.get("details", {}))
    details[step.field] = value
    await state.update_data(details=details)

    await _advance(step, message, state, bot, settings)


async def _advance(
    step: Step,
    message: types.Message,
    state: FSMContext,
    bot: Bot,
    settings: Settings,
    edit: types.CallbackQuery | None = None,
) -> None:
    if step.next_state is not None:
        next_step = _BY_STATE[step.next_state]
        await state.set_state(next_step.state)
        text = _prompt_text(next_step)
        keyboard = _keyboard(next_step)
        if edit is not None:
            await edit_or_send(edit, text, keyboard)
        else:
            await message.answer(text, reply_markup=keyboard)
        return

    data = await state.get_data()
    if data.get("is_csr"):
        await _ask_passphrase(message, state, edit)
    else:
        await state.set_state(X509SG.choose_days)
        if edit is not None:
            await edit_or_send(edit, texts.X509_ASK_DAYS, kb.x509_days())
        else:
            await message.answer(texts.X509_ASK_DAYS, reply_markup=kb.x509_days())


async def _ask_passphrase(
    message: types.Message, state: FSMContext, edit: types.CallbackQuery | None = None
) -> None:
    await state.set_state(X509SG.get_passphrase)
    if edit is not None:
        await edit_or_send(edit, texts.X509_ASK_PASSPHRASE, kb.x509_passphrase())
    else:
        await message.answer(texts.X509_ASK_PASSPHRASE, reply_markup=kb.x509_passphrase())


@router.callback_query(X509SG.choose_days, F.data.startswith(CB.X509_DAYS_PREFIX))
async def x509_choose_days(query: types.CallbackQuery, state: FSMContext) -> None:
    await query.answer()
    raw = query.data.removeprefix(CB.X509_DAYS_PREFIX)
    if not raw.isdigit() or not (1 <= int(raw) <= 7300):
        await query.answer(texts.STALE_BUTTON, show_alert=True)
        return
    await state.update_data(days=int(raw))
    await _ask_passphrase(query.message, state, edit=query)


@router.callback_query(X509SG.get_passphrase, F.data == CB.X509_NO_PASSPHRASE)
async def x509_no_passphrase(
    query: types.CallbackQuery, state: FSMContext, bot: Bot, settings: Settings
) -> None:
    await query.answer()
    await safe_delete(query.message)
    await _generate(bot, query.message.chat.id, state, None, settings)


@router.message(X509SG.get_passphrase)
async def x509_with_passphrase(
    message: types.Message, state: FSMContext, bot: Bot, settings: Settings
) -> None:
    raw = (message.text or "").strip()
    await safe_delete(message)
    if not raw:
        await message.answer(texts.X509_ASK_PASSPHRASE, reply_markup=kb.x509_passphrase())
        return
    await _generate(bot, message.chat.id, state, raw.encode("utf-8"), settings)


async def _generate(
    bot: Bot, chat_id: int, state: FSMContext, passphrase: bytes | None, settings: Settings
) -> None:
    data = await state.get_data()
    is_csr = bool(data.get("is_csr"))
    details = dict(data.get("details", {}))
    days = int(data.get("days", 365))
    cn = details.get("CN", "")

    kind = texts.KIND_CSR if is_csr else texts.KIND_CERT
    kind_short = texts.KIND_CSR_SHORT if is_csr else texts.KIND_CERT_SHORT

    progress = await bot.send_message(chat_id, texts.X509_GENERATING.format(kind=kind))

    request = cert_service.CertRequest(
        is_csr=is_csr,
        details=details,
        days=days,
        passphrase=passphrase,
        key_size=settings.rsa_x509_key_size,
    )
    try:
        generated = await cert_service.generate(request)
    except Exception as exc:
        logger.exception("Ошибка генерации X.509")
        await progress.edit_text(
            texts.X509_ERROR.format(error=esc(str(exc)[:200])), reply_markup=kb.x509_after()
        )
        await state.set_data({})
        await state.set_state(X509SG.menu)
        return
    finally:
        passphrase = None

    stem = sanitize_filename(cn, fallback="certificate")

    await progress.edit_text(
        texts.X509_READY.format(kind_capitalized=kind_short, cn=esc(cn or "—"))
    )
    await bot.send_document(
        chat_id,
        BufferedInputFile(generated.document_pem, filename=f"{stem}{generated.document_suffix}"),
        caption=texts.X509_CAPTION_CSR if is_csr else texts.X509_CAPTION_CERT.format(days=days),
    )
    await bot.send_document(
        chat_id,
        BufferedInputFile(generated.private_key_pem, filename=f"{stem}.key"),
        caption=texts.X509_CAPTION_KEY,
    )
    await bot.send_message(chat_id, texts.X509_FOOTER, reply_markup=kb.x509_after())

    await state.set_data({})
    await state.set_state(X509SG.menu)
