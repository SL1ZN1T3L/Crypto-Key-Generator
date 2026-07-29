"""Инлайн-клавиатуры."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class CB:
    MAIN_MENU = "nav:main"
    CANCEL = "nav:cancel"

    SSH_MENU = "ssh:menu"
    SSH_GENERATE = "ssh:generate"
    SSH_EXPORT = "ssh:export"
    SSH_VALIDATE = "ssh:validate"
    SSH_KEY_RSA = "ssh:key:rsa"
    SSH_KEY_ED25519 = "ssh:key:ed25519"
    SSH_NO_PASSPHRASE = "ssh:nopass"
    SSH_EXPORT_START = "ssh:export:start"
    SSH_HOST_ACCEPT = "ssh:host:accept"
    SSH_HOST_REJECT = "ssh:host:reject"
    SSH_QUOTA = "ssh:quota"

    HASH_MENU = "hash:menu"
    HASH_INFO = "hash:info"
    HASH_ALGO_PREFIX = "hash:algo:"

    X509_MENU = "x509:menu"
    X509_SELF_SIGNED = "x509:self"
    X509_CSR = "x509:csr"
    X509_SKIP = "x509:skip"
    X509_DAYS_PREFIX = "x509:days:"
    X509_NO_PASSPHRASE = "x509:nopass"


HASH_ALGORITHMS: dict[str, str] = {
    "md5": "MD5",
    "sha1": "SHA-1",
    "sha256": "SHA-256",
    "sha512": "SHA-512",
    "blake2b": "BLAKE2b",
}

_BTN_MAIN = InlineKeyboardButton(text="🏠 Главное меню", callback_data=CB.MAIN_MENU)
_BTN_SSH_MENU = InlineKeyboardButton(text="⬅️ SSH-меню", callback_data=CB.SSH_MENU)
_BTN_CANCEL = InlineKeyboardButton(text="❌ Отмена", callback_data=CB.CANCEL)


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 SSH-ключи", callback_data=CB.SSH_MENU)],
        [InlineKeyboardButton(text="#️⃣ Хеширование", callback_data=CB.HASH_MENU)],
        [InlineKeyboardButton(text="🪪 X.509 Сертификаты", callback_data=CB.X509_MENU)],
    ])


def cancel_only() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_BTN_CANCEL]])


def ssh_menu(export_enabled: bool = True) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="🔑 Сгенерировать ключ", callback_data=CB.SSH_GENERATE)]]
    if export_enabled:
        rows.append([InlineKeyboardButton(
            text="📤 Экспортировать существующий", callback_data=CB.SSH_EXPORT)])
    rows.append([InlineKeyboardButton(text="🔎 Проверить публичный ключ", callback_data=CB.SSH_VALIDATE)])
    if export_enabled:
        rows.append([InlineKeyboardButton(text="📊 Мои лимиты", callback_data=CB.SSH_QUOTA)])
    rows.append([_BTN_MAIN])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ssh_key_types() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Ed25519 (рекомендуется)", callback_data=CB.SSH_KEY_ED25519)],
        [InlineKeyboardButton(text="RSA 4096", callback_data=CB.SSH_KEY_RSA)],
        [_BTN_SSH_MENU],
    ])


def ssh_passphrase() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Без секретной фразы", callback_data=CB.SSH_NO_PASSPHRASE)],
        [_BTN_CANCEL],
    ])


def ssh_offer_export(export_enabled: bool = True) -> InlineKeyboardMarkup:
    rows = []
    if export_enabled:
        rows.append([InlineKeyboardButton(
            text="🚀 Экспортировать на сервер", callback_data=CB.SSH_EXPORT_START)])
    rows.append([_BTN_SSH_MENU])
    rows.append([_BTN_MAIN])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ssh_validation_result() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔎 Проверить ещё один", callback_data=CB.SSH_VALIDATE)],
        [_BTN_SSH_MENU],
        [_BTN_MAIN],
    ])


def ssh_host_key_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отпечаток совпадает", callback_data=CB.SSH_HOST_ACCEPT)],
        [InlineKeyboardButton(text="🛑 Не совпадает / отмена", callback_data=CB.SSH_HOST_REJECT)],
    ])


def ssh_after_export() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_BTN_SSH_MENU], [_BTN_MAIN]])


def hash_algorithms() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key, label in HASH_ALGORITHMS.items():
        builder.button(text=label, callback_data=f"{CB.HASH_ALGO_PREFIX}{key}")
    builder.adjust(2, 2, 1)
    builder.row(InlineKeyboardButton(text="ℹ️ Справка по алгоритмам", callback_data=CB.HASH_INFO))
    builder.row(_BTN_MAIN)
    return builder.as_markup()


def hash_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Выбор алгоритма", callback_data=CB.HASH_MENU)],
        [_BTN_MAIN],
    ])


def x509_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛡️ Самоподписанный сертификат", callback_data=CB.X509_SELF_SIGNED)],
        [InlineKeyboardButton(text="📝 Запрос CSR", callback_data=CB.X509_CSR)],
        [_BTN_MAIN],
    ])


def x509_skip() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Пропустить", callback_data=CB.X509_SKIP)],
        [_BTN_CANCEL],
    ])


def x509_days() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="90 дней", callback_data=f"{CB.X509_DAYS_PREFIX}90"),
         InlineKeyboardButton(text="365 дней", callback_data=f"{CB.X509_DAYS_PREFIX}365")],
        [InlineKeyboardButton(text="825 дней", callback_data=f"{CB.X509_DAYS_PREFIX}825"),
         InlineKeyboardButton(text="3650 дней", callback_data=f"{CB.X509_DAYS_PREFIX}3650")],
        [_BTN_CANCEL],
    ])


def x509_passphrase() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Без секретной фразы", callback_data=CB.X509_NO_PASSPHRASE)],
        [_BTN_CANCEL],
    ])


def x509_after() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🪪 Ещё один", callback_data=CB.X509_MENU)],
        [_BTN_MAIN],
    ])
