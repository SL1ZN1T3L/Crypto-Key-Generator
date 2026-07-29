"""Вычисление хешей."""

from __future__ import annotations

import asyncio
import hashlib
from typing import BinaryIO, Callable

_CHUNK = 1024 * 1024

_FACTORIES: dict[str, Callable[[], "hashlib._Hash"]] = {
    "md5": lambda: hashlib.md5(usedforsecurity=False),
    "sha1": lambda: hashlib.sha1(usedforsecurity=False),
    "sha256": hashlib.sha256,
    "sha512": hashlib.sha512,
    "blake2b": lambda: hashlib.blake2b(digest_size=64),
}


class UnknownAlgorithm(ValueError):
    pass


def _new(algorithm: str):
    factory = _FACTORIES.get(algorithm)
    if factory is None:
        raise UnknownAlgorithm(algorithm)
    return factory()


def _hash_bytes_sync(data: bytes, algorithm: str) -> str:
    digest = _new(algorithm)
    for offset in range(0, len(data), _CHUNK):
        digest.update(data[offset:offset + _CHUNK])
    return digest.hexdigest()


def _hash_stream_sync(stream: BinaryIO, algorithm: str) -> str:
    digest = _new(algorithm)
    while chunk := stream.read(_CHUNK):
        digest.update(chunk)
    return digest.hexdigest()


async def hash_text(text: str, algorithm: str) -> tuple[str, int]:
    """Возвращает (hex-дайджест, длина в байтах UTF-8)."""
    data = text.encode("utf-8")
    value = await asyncio.to_thread(_hash_bytes_sync, data, algorithm)
    return value, len(data)


async def hash_stream(stream: BinaryIO, algorithm: str) -> str:
    return await asyncio.to_thread(_hash_stream_sync, stream, algorithm)
