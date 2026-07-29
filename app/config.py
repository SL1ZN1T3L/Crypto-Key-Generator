"""Конфигурация приложения. Единственное место, где читается окружение."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env", override=False)


def _get_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_id_set(name: str) -> frozenset[int]:
    raw = os.getenv(name, "")
    ids: set[int] = set()
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.add(int(chunk))
        except ValueError:
            continue
    return frozenset(ids)


class ConfigError(RuntimeError):
    """Ошибка конфигурации, при которой запуск невозможен."""


@dataclass(frozen=True)
class Settings:
    bot_token: str

    allowed_user_ids: frozenset[int] = field(default_factory=frozenset)
    ssh_export_enabled: bool = True
    allow_private_targets: bool = False

    probe_user_hour: int = 15
    probe_user_day: int = 40
    probe_global_hour: int = 200
    auth_user_hour: int = 10
    auth_user_day: int = 25
    auth_global_hour: int = 120
    fail_user_host: int = 3
    fail_user_total: int = 8
    distinct_hosts_day: int = 8
    max_concurrent_ssh: int = 5

    redis_url: str = ""

    rate_limit_seconds: float = 0.7
    heavy_op_cooldown_seconds: int = 10
    max_file_size_mb: int = 20
    ssh_connect_timeout: int = 15
    twofa_timeout: int = 120
    ssh_default_port: int = 22

    rsa_ssh_key_size: int = 4096
    rsa_x509_key_size: int = 3072

    log_level: str = "INFO"
    log_to_file: bool = False
    log_dir: Path = BASE_DIR / "logs"
    healthcheck_file: Path = Path("/tmp/bot-healthy")
    heartbeat_interval: int = 30

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def access_is_restricted(self) -> bool:
        return bool(self.allowed_user_ids)

    def build_quota_config(self):
        from .services.quota import Limit, QuotaConfig

        return QuotaConfig(
            probe_user_hour=Limit(self.probe_user_hour, 3600),
            probe_user_day=Limit(self.probe_user_day, 86400),
            probe_global_hour=Limit(self.probe_global_hour, 3600),
            auth_user_hour=Limit(self.auth_user_hour, 3600),
            auth_user_day=Limit(self.auth_user_day, 86400),
            auth_global_hour=Limit(self.auth_global_hour, 3600),
            fail_user_host=Limit(self.fail_user_host, 3600),
            fail_user_total=Limit(self.fail_user_total, 3600),
            distinct_hosts_day=Limit(self.distinct_hosts_day, 86400),
            max_concurrent=self.max_concurrent_ssh,
        )


def load_settings() -> Settings:
    token = (os.getenv("BOT_TOKEN") or "").strip()
    if not token:
        raise ConfigError(
            "BOT_TOKEN не задан.\n"
            "  • локально: скопируйте .env.example -> .env и впишите токен от @BotFather\n"
            "  • docker:   docker run --env-file .env ... либо environment: в compose"
        )
    if ":" not in token or not token.split(":", 1)[0].isdigit():
        raise ConfigError("BOT_TOKEN имеет некорректный формат (ожидается 123456789:AA...).")

    return Settings(
        bot_token=token,
        allowed_user_ids=_get_id_set("ALLOWED_USER_IDS"),
        ssh_export_enabled=_get_bool("SSH_EXPORT_ENABLED", True),
        allow_private_targets=_get_bool("ALLOW_PRIVATE_TARGETS", False),
        probe_user_hour=_get_int("QUOTA_PROBE_USER_HOUR", 15),
        probe_user_day=_get_int("QUOTA_PROBE_USER_DAY", 40),
        probe_global_hour=_get_int("QUOTA_PROBE_GLOBAL_HOUR", 200),
        auth_user_hour=_get_int("QUOTA_AUTH_USER_HOUR", 10),
        auth_user_day=_get_int("QUOTA_AUTH_USER_DAY", 25),
        auth_global_hour=_get_int("QUOTA_AUTH_GLOBAL_HOUR", 120),
        fail_user_host=_get_int("QUOTA_FAIL_USER_HOST", 3),
        fail_user_total=_get_int("QUOTA_FAIL_USER_TOTAL", 8),
        distinct_hosts_day=_get_int("QUOTA_DISTINCT_HOSTS_DAY", 8),
        max_concurrent_ssh=_get_int("QUOTA_MAX_CONCURRENT_SSH", 5),
        redis_url=(os.getenv("REDIS_URL") or "").strip(),
        rate_limit_seconds=float(os.getenv("RATE_LIMIT_SECONDS", "0.7")),
        heavy_op_cooldown_seconds=_get_int("HEAVY_OP_COOLDOWN_SECONDS", 10),
        max_file_size_mb=_get_int("MAX_FILE_SIZE_MB", 20),
        ssh_connect_timeout=_get_int("SSH_CONNECT_TIMEOUT", 15),
        twofa_timeout=_get_int("TWOFA_TIMEOUT", 120),
        ssh_default_port=_get_int("SSH_DEFAULT_PORT", 22),
        rsa_ssh_key_size=_get_int("RSA_SSH_KEY_SIZE", 4096),
        rsa_x509_key_size=_get_int("RSA_X509_KEY_SIZE", 3072),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        log_to_file=_get_bool("LOG_TO_FILE", False),
        log_dir=Path(os.getenv("LOG_DIR", str(BASE_DIR / "logs"))),
        healthcheck_file=Path(os.getenv("HEALTHCHECK_FILE", "/tmp/bot-healthy")),
        heartbeat_interval=_get_int("HEARTBEAT_INTERVAL", 30),
    )
