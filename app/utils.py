"""Мелкие утилиты: экранирование, санитизация имён файлов, отпечатки."""

from __future__ import annotations

import base64
import hashlib
import html
import re
import unicodedata
from typing import NamedTuple

_FILENAME_BAD = re.compile(r"[^\w.\-]+", re.UNICODE)
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9\-._]+$"
)
_USERNAME_RE = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._\-]{0,31}$")


def esc(value: object) -> str:
    """Экранирование произвольных данных для HTML-разметки Telegram."""
    return html.escape(str(value), quote=False)


def sanitize_filename(name: str, fallback: str, max_length: int = 64) -> str:
    """Безопасное имя файла: без слэшей, переводов строк и юникод-сюрпризов."""
    normalized = unicodedata.normalize("NFKD", name or "")
    cleaned = _FILENAME_BAD.sub("_", normalized).strip("._-")
    if not cleaned:
        cleaned = fallback
    return cleaned[:max_length]


def human_size(num_bytes: int) -> str:
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.2f} МБ"
    if num_bytes >= 1024:
        return f"{num_bytes / 1024:.1f} КБ"
    return f"{num_bytes} байт"


class SshTarget(NamedTuple):
    username: str
    host: str
    port: int

    @property
    def display(self) -> str:
        if self.port == 22:
            return f"{self.username}@{self.host}"
        return f"{self.username}@{self.host}:{self.port}"

    @property
    def ssh_command(self) -> str:
        if self.port == 22:
            return f"{self.username}@{self.host}"
        return f"-p {self.port} {self.username}@{self.host}"


def parse_ssh_target(raw: str, default_port: int = 22) -> SshTarget | None:
    """Разбирает ``user@host`` / ``user@host:port``."""
    raw = (raw or "").strip()
    if not raw or "@" not in raw or len(raw) > 300:
        return None
    if any(ch.isspace() for ch in raw):
        return None

    username, _, hostpart = raw.partition("@")
    if not _USERNAME_RE.match(username):
        return None

    port = default_port
    host = hostpart

    if hostpart.startswith("["):
        closing = hostpart.find("]")
        if closing == -1:
            return None
        host = hostpart[1:closing]
        tail = hostpart[closing + 1:]
        if tail:
            if not tail.startswith(":"):
                return None
            if not tail[1:].isdigit():
                return None
            port = int(tail[1:])
    elif hostpart.count(":") == 1:
        host, _, port_raw = hostpart.partition(":")
        if not port_raw.isdigit():
            return None
        port = int(port_raw)
    elif hostpart.count(":") > 1:
        host = hostpart

    if not host or not (1 <= port <= 65535):
        return None
    if ":" not in host and not _HOSTNAME_RE.match(host):
        return None

    return SshTarget(username=username, host=host, port=port)


def ssh_fingerprints(openssh_public_line: bytes) -> dict[str, str]:
    """Отпечатки в тех же форматах, что показывает ``ssh-keygen -lf``."""
    result: dict[str, str] = {}
    parts = openssh_public_line.split()
    if len(parts) < 2:
        return result
    try:
        blob = base64.b64decode(parts[1], validate=True)
    except (ValueError, TypeError):
        return result

    sha256_b64 = base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
    result["SHA256"] = f"SHA256:{sha256_b64}"

    md5_hex = hashlib.md5(blob, usedforsecurity=False).hexdigest()
    result["MD5"] = "MD5:" + ":".join(md5_hex[i:i + 2] for i in range(0, len(md5_hex), 2))
    return result


def extract_key_comment(openssh_public_line: str) -> str:
    parts = openssh_public_line.strip().split(None, 2)
    if len(parts) >= 3:
        return parts[2].strip()
    return ""
