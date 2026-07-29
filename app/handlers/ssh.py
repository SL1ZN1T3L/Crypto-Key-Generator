"""SSH: генерация ключей, проверка публичного ключа, экспорт на сервер."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import asyncssh
from aiogram import Bot, F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile

from .. import keyboards as kb
from .. import texts
from ..config import Settings
from ..keyboards import CB
from ..middlewares import HeavyOperationLimiter
from ..services import keys as key_service
from ..services import netpolicy, ssh_export
from ..services.quota import SshQuota
from ..states import MainSG, SshSG
from ..utils import esc, extract_key_comment, parse_ssh_target, ssh_fingerprints
from .helpers import delete_by_id, edit_or_send, safe_delete

logger = logging.getLogger(__name__)
router = Router(name="ssh")

_background_tasks: set[asyncio.Task] = set()

_pending_2fa: dict[int, asyncio.Future[str]] = {}

_heavy = HeavyOperationLimiter(cooldown=10)

_ssh_semaphore = asyncio.Semaphore(5)


def configure_concurrency(max_concurrent: int) -> None:
    global _ssh_semaphore
    _ssh_semaphore = asyncio.Semaphore(max(1, max_concurrent))


@router.callback_query(F.data == CB.SSH_QUOTA)
async def ssh_quota_status(
    query: types.CallbackQuery, state: FSMContext, quota: SshQuota, settings: Settings
) -> None:
    await query.answer()
    rows = "\n".join(
        f"• {esc(name)}: <code>{esc(value)}</code>"
        for name, value in (await quota.usage(query.from_user.id)).items()
    )
    await state.set_state(SshSG.menu)
    await edit_or_send(
        query,
        texts.SSH_QUOTA_STATUS.format(rows=rows),
        kb.ssh_menu(settings.ssh_export_enabled),
    )


def _format_wait(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} с"
    if seconds < 3600:
        return f"{seconds // 60} мин"
    return f"{seconds // 3600} ч {(seconds % 3600) // 60} мин"


async def _deny(message: types.Message, verdict) -> None:
    await message.answer(
        texts.SSH_QUOTA_EXCEEDED.format(
            reason=texts.SSH_QUOTA_REASONS.get(verdict.reason, "Лимит исчерпан."),
            wait=_format_wait(verdict.retry_after),
        ),
        reply_markup=kb.ssh_after_export(),
    )


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


@router.callback_query(F.data == CB.SSH_MENU)
async def ssh_menu(query: types.CallbackQuery, state: FSMContext, settings: Settings) -> None:
    await query.answer()
    await state.set_state(SshSG.menu)
    await edit_or_send(query, texts.SSH_MENU, kb.ssh_menu(settings.ssh_export_enabled))


@router.callback_query(SshSG.menu, F.data == CB.SSH_GENERATE)
async def ssh_choose_type(query: types.CallbackQuery, state: FSMContext) -> None:
    await query.answer()
    await state.set_state(SshSG.choose_key_type)
    await edit_or_send(query, texts.SSH_CHOOSE_TYPE, kb.ssh_key_types())


@router.callback_query(SshSG.choose_key_type, F.data.in_({CB.SSH_KEY_RSA, CB.SSH_KEY_ED25519}))
async def ssh_ask_passphrase(query: types.CallbackQuery, state: FSMContext) -> None:
    await query.answer()
    key_type = "rsa" if query.data == CB.SSH_KEY_RSA else "ed25519"
    await state.update_data(key_type=key_type)
    await state.set_state(SshSG.get_passphrase)
    await edit_or_send(query, texts.SSH_ASK_PASSPHRASE, kb.ssh_passphrase())


@router.callback_query(SshSG.get_passphrase, F.data == CB.SSH_NO_PASSPHRASE)
async def ssh_generate_no_passphrase(
    query: types.CallbackQuery, state: FSMContext, bot: Bot, settings: Settings
) -> None:
    await query.answer()
    await safe_delete(query.message)
    await _generate_and_send(bot, query.from_user.id, query.message.chat.id, state, None, settings)


@router.message(SshSG.get_passphrase)
async def ssh_generate_with_passphrase(
    message: types.Message, state: FSMContext, bot: Bot, settings: Settings
) -> None:
    raw = (message.text or "").strip()
    await safe_delete(message)
    if not raw:
        await message.answer(texts.SSH_ASK_PASSPHRASE, reply_markup=kb.ssh_passphrase())
        return
    await _generate_and_send(
        bot, message.from_user.id, message.chat.id, state, raw.encode("utf-8"), settings
    )


async def _generate_and_send(
    bot: Bot,
    user_id: int,
    chat_id: int,
    state: FSMContext,
    passphrase: bytes | None,
    settings: Settings,
) -> None:
    data = await state.get_data()
    key_type = data.get("key_type", "ed25519")

    if key_type == "rsa":
        wait = _heavy.check(user_id)
        if wait:
            await bot.send_message(chat_id, texts.HEAVY_COOLDOWN.format(seconds=wait))
            return
        _heavy.mark(user_id)

    progress = await bot.send_message(chat_id, texts.SSH_GENERATING)
    try:
        pair = await key_service.generate_keypair(
            key_type,
            passphrase,
            rsa_bits=settings.rsa_ssh_key_size,
            comment=f"crypto-bot-{datetime.now(timezone.utc):%Y%m%d}",
        )
    except Exception as exc:
        logger.exception("Ошибка генерации SSH-ключа")
        await progress.edit_text(texts.GENERIC_ERROR)
        await state.set_state(SshSG.menu)
        return
    finally:
        passphrase = None

    await progress.edit_text(texts.SSH_READY.format(key_info=esc(pair.key_info)))

    stem = pair.filename_stem
    await bot.send_document(
        chat_id,
        BufferedInputFile(pair.openssh_private, filename=stem),
        caption=texts.SSH_CAPTION_OPENSSH,
    )
    await bot.send_document(
        chat_id,
        BufferedInputFile(pair.pkcs8_private, filename=f"{stem}_pkcs8.pem"),
        caption=texts.SSH_CAPTION_PKCS8,
    )
    await bot.send_document(
        chat_id,
        BufferedInputFile(pair.openssh_public, filename=f"{stem}.pub"),
        caption=texts.SSH_PUBLIC_KEY.format(
            public_key=esc(pair.openssh_public.decode("utf-8", "replace"))
        ),
    )

    if pair.encryption_failed:
        await bot.send_message(
            chat_id,
            "⚠️ В окружении нет <code>bcrypt</code>, поэтому зашифровать ключ "
            "не удалось. Установите пакет и сгенерируйте ключ заново.",
        )
    await bot.send_message(chat_id, texts.SSH_PROTECTED if pair.encrypted else texts.SSH_UNPROTECTED)

    await state.set_data({"public_key": pair.openssh_public.decode("utf-8")})
    await state.set_state(SshSG.offer_export)
    await bot.send_message(
        chat_id,
        texts.SSH_OFFER_EXPORT,
        reply_markup=kb.ssh_offer_export(settings.ssh_export_enabled),
    )


@router.callback_query(F.data == CB.SSH_VALIDATE)
async def ssh_ask_key_to_validate(query: types.CallbackQuery, state: FSMContext) -> None:
    await query.answer()
    await state.set_state(SshSG.wait_key_to_validate)
    await edit_or_send(query, texts.SSH_ASK_KEY_TO_VALIDATE, kb.cancel_only())


@router.message(SshSG.wait_key_to_validate)
async def ssh_validate_key(message: types.Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw:
        await message.answer(texts.SSH_INVALID_PUBLIC_KEY, reply_markup=kb.cancel_only())
        return

    progress = await message.answer(texts.SSH_ANALYZING)
    try:
        info = key_service.inspect_public_key(raw)
    except Exception as exc:
        logger.info("Некорректный публичный ключ: %s", exc)
        await progress.edit_text(
            texts.SSH_INVALID_PUBLIC_KEY, reply_markup=kb.ssh_validation_result()
        )
        return

    fps = ssh_fingerprints(info.normalized_line)
    comment = extract_key_comment(raw)
    await progress.edit_text(
        texts.SSH_VALIDATION_RESULT.format(
            key_type=esc(info.key_type),
            key_size=esc(info.key_size),
            comment=f"<code>{esc(comment)}</code>" if comment else "<i>отсутствует</i>",
            sha256=esc(fps.get("SHA256", "н/д")),
            md5=esc(fps.get("MD5", "н/д")),
        ),
        reply_markup=kb.ssh_validation_result(),
    )
    await state.set_state(SshSG.menu)


@router.callback_query(F.data == CB.SSH_EXPORT)
async def ssh_ask_existing_key(
    query: types.CallbackQuery, state: FSMContext, settings: Settings
) -> None:
    await query.answer()
    if not settings.ssh_export_enabled:
        await edit_or_send(query, texts.SSH_EXPORT_DISABLED, kb.ssh_menu(False))
        return
    await state.set_state(SshSG.get_existing_public_key)
    await edit_or_send(query, texts.SSH_ASK_EXISTING_PUBLIC_KEY, kb.cancel_only())


@router.message(SshSG.get_existing_public_key)
async def ssh_accept_existing_key(message: types.Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    try:
        info = key_service.inspect_public_key(raw)
    except Exception:
        await message.answer(texts.SSH_INVALID_PUBLIC_KEY, reply_markup=kb.cancel_only())
        return

    await state.update_data(
        public_key=info.original_line,
        key_type_label=info.key_type,
    )
    await state.set_state(SshSG.get_target)
    await message.answer(f"{texts.SSH_KEY_ACCEPTED}\n\n{texts.SSH_ASK_SERVER}", reply_markup=kb.cancel_only())


@router.callback_query(SshSG.offer_export, F.data == CB.SSH_EXPORT_START)
async def ssh_ask_target(
    query: types.CallbackQuery, state: FSMContext, settings: Settings
) -> None:
    await query.answer()
    if not settings.ssh_export_enabled:
        await edit_or_send(query, texts.SSH_EXPORT_DISABLED, kb.ssh_menu(False))
        return
    await state.set_state(SshSG.get_target)
    await edit_or_send(query, texts.SSH_ASK_SERVER, kb.cancel_only())


@router.message(SshSG.get_target)
async def ssh_process_target(
    message: types.Message, state: FSMContext, settings: Settings, quota: SshQuota
) -> None:
    target = parse_ssh_target((message.text or ""), settings.ssh_default_port)
    if target is None:
        await message.answer(texts.SSH_BAD_SERVER, reply_markup=kb.cancel_only())
        return

    data = await state.get_data()
    if not data.get("public_key"):
        await state.clear()
        await state.set_state(MainSG.menu)
        await message.answer(texts.SSH_NO_PUBLIC_KEY, reply_markup=kb.main_menu())
        return

    user_id = message.from_user.id
    verdict = await quota.check_probe(user_id, target.host)
    if not verdict.allowed:
        logger.warning("Квота probe исчерпана: user=%s reason=%s", user_id, verdict.reason)
        await _deny(message, verdict)
        await state.set_state(SshSG.menu)
        return

    progress = await message.answer(
        texts.SSH_FETCHING_HOST_KEY.format(target=esc(target.display))
    )

    try:
        resolved = await netpolicy.resolve_target(
            target.host, target.port, allow_private=settings.allow_private_targets
        )
    except netpolicy.TargetRejected as exc:
        logger.warning("Адрес отклонён политикой: user=%s target=%s (%s)",
                       user_id, target.display, exc)
        await progress.edit_text(
            texts.SSH_TARGET_REJECTED.format(error=esc(str(exc)[:200])),
            reply_markup=kb.ssh_after_export(),
        )
        await state.set_state(SshSG.menu)
        return

    await quota.record_probe(user_id, target.host)

    try:
        host_key = await ssh_export.fetch_host_key(
            target, settings.ssh_connect_timeout, connect_host=resolved.ip
        )
    except ssh_export.HostKeyError as exc:
        await progress.edit_text(
            texts.SSH_HOST_KEY_ERROR.format(target=esc(target.display), error=esc(str(exc)[:200])),
            reply_markup=kb.ssh_after_export(),
        )
        await state.set_state(SshSG.menu)
        return

    await state.update_data(
        target_raw=target.display,
        target_user=target.username,
        target_host=target.host,
        target_port=target.port,
        target_ip=resolved.ip,
        host_key_export=host_key.key.export_public_key().decode("utf-8"),
    )
    await state.set_state(SshSG.confirm_host_key)
    await progress.edit_text(
        texts.SSH_CONFIRM_HOST_KEY.format(
            target=esc(target.display),
            key_type=esc(host_key.algorithm),
            fingerprint=esc(host_key.fingerprint),
            key_file=esc(host_key.file_hint),
        ),
        reply_markup=kb.ssh_host_key_confirm(),
    )


@router.callback_query(SshSG.confirm_host_key, F.data == CB.SSH_HOST_REJECT)
async def ssh_reject_host_key(query: types.CallbackQuery, state: FSMContext) -> None:
    await query.answer()
    await state.clear()
    await state.set_state(SshSG.menu)
    await edit_or_send(query, texts.CANCELLED, kb.ssh_menu())


@router.callback_query(SshSG.confirm_host_key, F.data == CB.SSH_HOST_ACCEPT)
async def ssh_accept_host_key(query: types.CallbackQuery, state: FSMContext) -> None:
    await query.answer()
    data = await state.get_data()
    prompt = await query.message.answer(
        texts.SSH_ASK_PASSWORD.format(
            user=esc(data.get("target_user", "")),
            target=esc(data.get("target_raw", "")),
        )
    )
    await state.update_data(password_prompt_id=prompt.message_id)
    await state.set_state(SshSG.wait_password)
    await safe_delete(query.message)


@router.message(SshSG.wait_password)
async def ssh_receive_password(
    message: types.Message, state: FSMContext, bot: Bot, settings: Settings, quota: SshQuota
) -> None:
    password = message.text or ""
    chat_id = message.chat.id
    await safe_delete(message)

    data = await state.get_data()
    await delete_by_id(bot, chat_id, data.get("password_prompt_id"))

    target = parse_ssh_target(
        f"{data.get('target_user')}@{data.get('target_host')}:{data.get('target_port')}",
        settings.ssh_default_port,
    )
    public_key = data.get("public_key")
    host_key_export = data.get("host_key_export")

    if not (target and public_key and host_key_export):
        await state.clear()
        await state.set_state(MainSG.menu)
        await bot.send_message(chat_id, texts.SSH_NO_PUBLIC_KEY, reply_markup=kb.main_menu())
        return

    user_id = message.from_user.id
    verdict = await quota.check_auth(user_id, target.host)
    if not verdict.allowed:
        logger.warning("Квота auth исчерпана: user=%s reason=%s", user_id, verdict.reason)
        await state.set_data({})
        await state.set_state(SshSG.menu)
        await _deny(message, verdict)
        return
    await quota.record_auth(user_id)

    host_key = asyncssh.import_public_key(host_key_export)

    await state.set_state(SshSG.wait_2fa)
    _spawn(
        _run_export(
            bot=bot,
            chat_id=chat_id,
            user_id=user_id,
            state=state,
            target=target,
            connect_ip=data.get("target_ip"),
            password=password,
            public_key=public_key,
            host_key=host_key,
            settings=settings,
            quota=quota,
        )
    )


async def _run_export(
    *,
    bot: Bot,
    chat_id: int,
    user_id: int,
    state: FSMContext,
    target,
    connect_ip: str | None,
    password: str,
    public_key: str,
    host_key,
    settings: Settings,
    quota: SshQuota,
) -> None:
    progress = await bot.send_message(
        chat_id, texts.SSH_AUTHENTICATING.format(target=esc(target.display))
    )

    async def prompt_2fa(prompt_text: str) -> str:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        _pending_2fa[user_id] = future
        msg = await bot.send_message(
            chat_id, texts.SSH_2FA_PROMPT.format(prompt=esc(prompt_text))
        )
        try:
            return await asyncio.wait_for(future, timeout=settings.twofa_timeout)
        except asyncio.TimeoutError:
            await bot.send_message(chat_id, texts.SSH_2FA_TIMEOUT)
            raise
        finally:
            _pending_2fa.pop(user_id, None)
            await delete_by_id(bot, chat_id, msg.message_id)

    try:
        async with _ssh_semaphore:
            result = await ssh_export.export_public_key(
                target=target,
                password=password,
                public_key_line=public_key,
                host_key=host_key,
                prompt_callback=prompt_2fa,
                connect_timeout=settings.ssh_connect_timeout,
                connect_host=connect_ip,
            )
    except ssh_export.AuthError:
        await quota.record_failure(user_id, target.host)
        await progress.edit_text(
            texts.SSH_AUTH_FAILED.format(user=esc(target.username)),
            reply_markup=kb.ssh_after_export(),
        )
    except ssh_export.HostKeyError as exc:
        await progress.edit_text(
            texts.SSH_HOST_KEY_ERROR.format(
                target=esc(target.display), error=esc(str(exc)[:200])
            ),
            reply_markup=kb.ssh_after_export(),
        )
    except ssh_export.RemoteError as exc:
        await progress.edit_text(
            texts.SSH_EXPORT_FAILED.format(error=esc(str(exc)[:300])),
            reply_markup=kb.ssh_after_export(),
        )
    except asyncio.TimeoutError:
        await progress.edit_text(
            texts.SSH_CONNECT_FAILED.format(
                target=esc(target.display), error="время ожидания истекло"
            ),
            reply_markup=kb.ssh_after_export(),
        )
    except Exception as exc:
        logger.exception("Непредвиденная ошибка экспорта SSH-ключа")
        await progress.edit_text(
            texts.SSH_CONNECT_FAILED.format(
                target=esc(target.display), error=esc(str(exc)[:200])
            ),
            reply_markup=kb.ssh_after_export(),
        )
    else:
        await quota.record_success(user_id, target.host)
        template = (
            texts.SSH_EXPORT_EXISTS
            if result is ssh_export.ExportResult.EXISTS
            else texts.SSH_EXPORT_ADDED
        )
        await progress.edit_text(
            template.format(target=esc(target.display), ssh_cmd=esc(target.ssh_command)),
            reply_markup=kb.ssh_after_export(),
        )
    finally:
        password = ""
        _pending_2fa.pop(user_id, None)
        await state.set_data({})
        await state.set_state(SshSG.menu)


@router.message(SshSG.wait_2fa)
async def ssh_receive_2fa(message: types.Message) -> None:
    future = _pending_2fa.get(message.from_user.id)
    await safe_delete(message)
    if future is None or future.done():
        return
    future.set_result((message.text or "").strip())
