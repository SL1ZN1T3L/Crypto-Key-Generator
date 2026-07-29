"""Квоты на SSH-операции для публичного бота."""

from __future__ import annotations

from dataclasses import dataclass

from .quota_backend import Limit, MemoryBackend, QuotaBackend

__all__ = ["Limit", "QuotaConfig", "SshQuota", "Verdict", "ALLOWED"]


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason: str = ""
    retry_after: int = 0


ALLOWED = Verdict(allowed=True)


@dataclass(frozen=True)
class QuotaConfig:
    probe_user_hour: Limit = Limit(15, 3600)
    probe_user_day: Limit = Limit(40, 86400)
    probe_global_hour: Limit = Limit(200, 3600)

    auth_user_hour: Limit = Limit(10, 3600)
    auth_user_day: Limit = Limit(25, 86400)
    auth_global_hour: Limit = Limit(120, 3600)

    fail_user_host: Limit = Limit(3, 3600)
    fail_user_total: Limit = Limit(8, 3600)

    distinct_hosts_day: Limit = Limit(8, 86400)

    max_concurrent: int = 5


class SshQuota:
    """Все проверки перед SSH-операциями в одном месте."""

    def __init__(
        self, config: QuotaConfig | None = None, backend: QuotaBackend | None = None
    ) -> None:
        self.config = config or QuotaConfig()
        self.backend: QuotaBackend = backend or MemoryBackend()


    @staticmethod
    def _probe_key(user_id: int) -> str:
        return f"probe:{user_id}"

    @staticmethod
    def _auth_key(user_id: int) -> str:
        return f"auth:{user_id}"

    @staticmethod
    def _fail_key(user_id: int) -> str:
        return f"fail:{user_id}"

    @staticmethod
    def _fail_host_key(user_id: int, host: str) -> str:
        return f"failhost:{user_id}:{host.lower()}"

    @staticmethod
    def _hosts_key(user_id: int) -> str:
        return f"hosts:{user_id}"


    async def _check_failures(self, user_id: int, host: str) -> Verdict | None:
        cfg = self.config
        wait = await self.backend.window_would_exceed(
            self._fail_host_key(user_id, host), cfg.fail_user_host
        )
        if wait:
            return Verdict(False, "fail_host", wait)

        wait = await self.backend.window_would_exceed(
            self._fail_key(user_id), cfg.fail_user_total
        )
        if wait:
            return Verdict(False, "fail_total", wait)
        return None

    async def check_probe(self, user_id: int, host: str) -> Verdict:
        """Перед запросом ключа хоста."""
        cfg = self.config

        verdict = await self._check_failures(user_id, host)
        if verdict is not None:
            return verdict

        wait = await self.backend.distinct_would_exceed(
            self._hosts_key(user_id), host.lower(), cfg.distinct_hosts_day
        )
        if wait:
            return Verdict(False, "distinct_hosts", wait)

        for limit, reason in (
            (cfg.probe_user_hour, "probe_hour"),
            (cfg.probe_user_day, "probe_day"),
        ):
            wait = await self.backend.window_would_exceed(self._probe_key(user_id), limit)
            if wait:
                return Verdict(False, reason, wait)

        wait = await self.backend.window_would_exceed("probe:*", cfg.probe_global_hour)
        if wait:
            return Verdict(False, "probe_global", wait)

        return ALLOWED

    async def record_probe(self, user_id: int, host: str) -> None:
        cfg = self.config
        await self.backend.window_record(self._probe_key(user_id), cfg.probe_user_day.window_seconds)
        await self.backend.window_record("probe:*", cfg.probe_global_hour.window_seconds)
        await self.backend.distinct_record(
            self._hosts_key(user_id), host.lower(), cfg.distinct_hosts_day.window_seconds
        )

    async def check_auth(self, user_id: int, host: str) -> Verdict:
        """Перед подключением с паролем."""
        cfg = self.config

        verdict = await self._check_failures(user_id, host)
        if verdict is not None:
            return verdict

        for limit, reason in (
            (cfg.auth_user_hour, "auth_hour"),
            (cfg.auth_user_day, "auth_day"),
        ):
            wait = await self.backend.window_would_exceed(self._auth_key(user_id), limit)
            if wait:
                return Verdict(False, reason, wait)

        wait = await self.backend.window_would_exceed("auth:*", cfg.auth_global_hour)
        if wait:
            return Verdict(False, "auth_global", wait)

        return ALLOWED

    async def record_auth(self, user_id: int) -> None:
        cfg = self.config
        await self.backend.window_record(self._auth_key(user_id), cfg.auth_user_day.window_seconds)
        await self.backend.window_record("auth:*", cfg.auth_global_hour.window_seconds)

    async def record_failure(self, user_id: int, host: str) -> None:
        cfg = self.config
        await self.backend.window_record(
            self._fail_host_key(user_id, host), cfg.fail_user_host.window_seconds
        )
        await self.backend.window_record(
            self._fail_key(user_id), cfg.fail_user_total.window_seconds
        )

    async def record_success(self, user_id: int, host: str) -> None:
        """Удачный вход снимает счётчик промахов по этому хосту."""
        await self.backend.window_clear(self._fail_host_key(user_id, host))


    async def usage(self, user_id: int) -> dict[str, str]:
        cfg = self.config
        auth_h = await self.backend.window_count(self._auth_key(user_id), 3600)
        auth_d = await self.backend.window_count(self._auth_key(user_id), 86400)
        hosts_d = await self.backend.distinct_count(self._hosts_key(user_id), 86400)
        fails_h = await self.backend.window_count(self._fail_key(user_id), 3600)
        return {
            "Подключений за час": f"{auth_h} / {cfg.auth_user_hour.max_events}",
            "Подключений за сутки": f"{auth_d} / {cfg.auth_user_day.max_events}",
            "Разных серверов за сутки": f"{hosts_d} / {cfg.distinct_hosts_day.max_events}",
            "Неудачных входов за час": f"{fails_h} / {cfg.fail_user_total.max_events}",
        }

    async def close(self) -> None:
        await self.backend.close()
