"""Экспорт публичного ключа на удалённый сервер."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable

import asyncssh

from ..utils import SshTarget

logger = logging.getLogger(__name__)

_REMOTE_SCRIPT = r"""
set -eu
umask 077
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
AK="$HOME/.ssh/authorized_keys"
[ -f "$AK" ] || : > "$AK"
chmod 600 "$AK"
KEY=$(cat)
if grep -qxF -- "$KEY" "$AK"; then
    echo "EXISTS"
else
    if [ -s "$AK" ] && [ -n "$(tail -c 1 "$AK")" ]; then
        printf '\n' >> "$AK"
    fi
    printf '%s\n' "$KEY" >> "$AK"
    echo "ADDED"
fi
"""


class ExportResult(str, Enum):
    ADDED = "ADDED"
    EXISTS = "EXISTS"


class HostKeyError(RuntimeError):
    pass


class AuthError(RuntimeError):
    pass


class RemoteError(RuntimeError):
    pass


@dataclass(frozen=True)
class HostKeyInfo:
    key: asyncssh.SSHKey
    algorithm: str
    fingerprint: str

    @property
    def file_hint(self) -> str:
        """Имя файла ключа на сервере — для подсказки в ssh-keygen -lf."""
        algo = self.algorithm
        if algo.startswith("ssh-ed25519"):
            return "ed25519"
        if algo.startswith("ssh-rsa") or algo.startswith("rsa-sha2"):
            return "rsa"
        if algo.startswith("ecdsa-"):
            return "ecdsa"
        return "ed25519"


async def fetch_host_key(
    target: SshTarget, timeout: int = 15, connect_host: str | None = None
) -> HostKeyInfo:
    """Получает ключ хоста, чтобы показать отпечаток пользователю."""
    try:
        key = await asyncio.wait_for(
            asyncssh.get_server_host_key(connect_host or target.host, target.port),
            timeout=timeout,
        )
    except asyncio.TimeoutError as exc:
        raise HostKeyError(f"таймаут {timeout} с при подключении") from exc
    except (OSError, asyncssh.Error) as exc:
        raise HostKeyError(str(exc) or exc.__class__.__name__) from exc

    if key is None:
        raise HostKeyError("сервер не предоставил ключ хоста")

    return HostKeyInfo(
        key=key,
        algorithm=key.get_algorithm(),
        fingerprint=key.get_fingerprint("sha256"),
    )


class _TwoFactorClient(asyncssh.SSHClient):
    """Клиент с поддержкой keyboard-interactive (2FA)."""

    def __init__(
        self,
        password: str,
        prompt_callback: Callable[[str], Awaitable[str]],
    ) -> None:
        self._password = password
        self._prompt_callback = prompt_callback
        self._password_offered = False
        self._kbdint_offered = False

    def password_auth_requested(self) -> str | None:
        if self._password_offered:
            return None
        self._password_offered = True
        return self._password

    def kbdint_auth_requested(self) -> str | None:
        if self._kbdint_offered:
            return None
        self._kbdint_offered = True
        return ""

    async def kbdint_challenge_received(self, name, instructions, lang, prompts):
        if not prompts:
            return []
        responses = []
        for prompt_text, _echo in prompts:
            if "password" in prompt_text.lower() or "пароль" in prompt_text.lower():
                responses.append(self._password)
                continue
            responses.append(await self._prompt_callback(prompt_text.strip()))
        return responses


async def export_public_key(
    target: SshTarget,
    password: str,
    public_key_line: str,
    host_key: asyncssh.SSHKey,
    prompt_callback: Callable[[str], Awaitable[str]],
    connect_timeout: int = 15,
    connect_host: str | None = None,
) -> ExportResult:
    """Дописывает публичный ключ в authorized_keys. Идемпотентно."""
    normalized = " ".join(public_key_line.split())

    def factory() -> _TwoFactorClient:
        return _TwoFactorClient(password, prompt_callback)

    try:
        async with asyncssh.connect(
            host=connect_host or target.host,
            port=target.port,
            username=target.username,
            client_factory=factory,
            known_hosts=([host_key], [], []),
            connect_timeout=connect_timeout,
            client_keys=None,
            agent_path=None,
            config=None,
        ) as conn:
            result = await conn.run(
                _REMOTE_SCRIPT,
                input=normalized + "\n",
                check=False,
                timeout=30,
            )
    except asyncssh.PermissionDenied as exc:
        raise AuthError(str(exc)) from exc
    except asyncssh.HostKeyNotVerifiable as exc:
        raise HostKeyError("ключ хоста изменился между проверкой и подключением") from exc
    except asyncio.TimeoutError as exc:
        raise RemoteError(f"таймаут {connect_timeout} с") from exc
    except (OSError, asyncssh.Error) as exc:
        raise RemoteError(str(exc) or exc.__class__.__name__) from exc

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    if result.exit_status != 0:
        raise RemoteError(stderr[:300] or f"код возврата {result.exit_status}")

    if stdout.endswith(ExportResult.EXISTS.value):
        return ExportResult.EXISTS
    if stdout.endswith(ExportResult.ADDED.value):
        return ExportResult.ADDED
    raise RemoteError(stderr[:300] or stdout[:300] or "неожиданный ответ сервера")
