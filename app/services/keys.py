"""Генерация и разбор SSH-ключей."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa
from cryptography.hazmat.primitives.serialization import load_ssh_public_key

logger = logging.getLogger(__name__)

KeyType = Literal["rsa", "ed25519"]


@dataclass(frozen=True)
class GeneratedKeyPair:
    key_type: KeyType
    key_info: str
    openssh_private: bytes
    pkcs8_private: bytes
    openssh_public: bytes
    encrypted: bool
    encryption_failed: bool = False

    @property
    def filename_stem(self) -> str:
        return "id_rsa" if self.key_type == "rsa" else "id_ed25519"


def _serialize(private_key, passphrase: bytes | None) -> tuple[bytes, bytes, bool, bool]:
    """Возвращает (openssh, pkcs8, encrypted, encryption_failed)."""
    encryption = (
        serialization.BestAvailableEncryption(passphrase)
        if passphrase
        else serialization.NoEncryption()
    )
    encryption_failed = False

    try:
        openssh = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.OpenSSH,
            encryption_algorithm=encryption,
        )
    except UnsupportedAlgorithm:
        logger.warning("bcrypt недоступен, приватный ключ будет без шифрования")
        encryption = serialization.NoEncryption()
        encryption_failed = True
        openssh = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.OpenSSH,
            encryption_algorithm=encryption,
        )

    pkcs8 = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=encryption,
    )
    return openssh, pkcs8, not isinstance(encryption, serialization.NoEncryption), encryption_failed


def _generate_sync(
    key_type: KeyType, passphrase: bytes | None, rsa_bits: int, comment: str = ""
) -> GeneratedKeyPair:
    if key_type == "rsa":
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=rsa_bits)
        key_info = f"RSA {rsa_bits} бит"
    else:
        private_key = ed25519.Ed25519PrivateKey.generate()
        key_info = "Ed25519"

    openssh, pkcs8, encrypted, encryption_failed = _serialize(private_key, passphrase)
    public = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    )
    if comment:
        public = public + b" " + comment.encode("utf-8")
    return GeneratedKeyPair(
        key_type=key_type,
        key_info=key_info,
        openssh_private=openssh,
        pkcs8_private=pkcs8,
        openssh_public=public,
        encrypted=encrypted,
        encryption_failed=encryption_failed,
    )


async def generate_keypair(
    key_type: KeyType,
    passphrase: bytes | None,
    rsa_bits: int = 4096,
    comment: str = "",
) -> GeneratedKeyPair:
    return await asyncio.to_thread(_generate_sync, key_type, passphrase, rsa_bits, comment)


@dataclass(frozen=True)
class PublicKeyInfo:
    key_type: str
    key_size: str
    normalized_line: bytes
    original_line: str


def inspect_public_key(raw: str) -> PublicKeyInfo:
    """Разбирает публичный ключ. Бросает ValueError на некорректном вводе."""
    candidate = " ".join(raw.split())
    if not candidate:
        raise ValueError("пустой ввод")

    public_key = load_ssh_public_key(candidate.encode("utf-8"))

    if isinstance(public_key, rsa.RSAPublicKey):
        key_type = "RSA"
        key_size = f"{public_key.key_size} бит"
    elif isinstance(public_key, ed25519.Ed25519PublicKey):
        key_type = "Ed25519"
        key_size = "256 бит"
    elif isinstance(public_key, ec.EllipticCurvePublicKey):
        key_type = f"ECDSA ({public_key.curve.name})"
        key_size = f"{public_key.curve.key_size} бит"
    else:
        key_type = type(public_key).__name__
        key_size = "н/д"

    normalized = public_key.public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    )
    return PublicKeyInfo(
        key_type=key_type,
        key_size=key_size,
        normalized_line=normalized,
        original_line=candidate,
    )
