"""Хранилища для счётчиков квот."""

from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Limit:
    max_events: int
    window_seconds: int

    def describe(self) -> str:
        if self.window_seconds >= 86400:
            unit = f"{self.window_seconds // 86400} сут"
        elif self.window_seconds >= 3600:
            unit = f"{self.window_seconds // 3600} ч"
        else:
            unit = f"{self.window_seconds // 60} мин"
        return f"{self.max_events} за {unit}"


class QuotaBackend(Protocol):
    """Интерфейс хранилища. Все методы асинхронные ради Redis."""

    async def window_would_exceed(self, key: str, limit: Limit) -> int: ...
    async def window_record(self, key: str, window: int) -> None: ...
    async def window_count(self, key: str, window: int) -> int: ...
    async def window_clear(self, key: str) -> None: ...
    async def distinct_would_exceed(self, key: str, value: str, limit: Limit) -> int: ...
    async def distinct_record(self, key: str, value: str, window: int) -> None: ...
    async def distinct_count(self, key: str, window: int) -> int: ...
    async def close(self) -> None: ...


class MemoryBackend:
    def __init__(self) -> None:
        self._windows: dict[str, deque[float]] = defaultdict(deque)
        self._distinct: dict[str, dict[str, float]] = defaultdict(dict)
        self._last_vacuum = time.time()

    def _count_in_window(self, key: str, window: int, now: float) -> tuple[int, float | None]:
        """Считает события в окне, НЕ удаляя ничего."""
        events = self._windows.get(key)
        if not events:
            return 0, None
        cutoff = now - window
        count = 0
        oldest: float | None = None
        for ts in events:
            if ts >= cutoff:
                count += 1
                if oldest is None:
                    oldest = ts
        return count, oldest

    def _prune_distinct(self, key: str, window: int, now: float) -> dict[str, float]:
        bucket = self._distinct[key]
        cutoff = now - window
        for value in [v for v, ts in bucket.items() if ts < cutoff]:
            del bucket[value]
        return bucket

    def _vacuum(self) -> None:
        now = time.time()
        if now - self._last_vacuum < 3600:
            return
        self._last_vacuum = now
        cutoff = now - 86400
        for key in list(self._windows):
            events = self._windows[key]
            while events and events[0] < cutoff:
                events.popleft()
            if not events:
                del self._windows[key]
        for key in list(self._distinct):
            if not self._prune_distinct(key, 86400, now):
                del self._distinct[key]

    async def window_would_exceed(self, key: str, limit: Limit) -> int:
        self._vacuum()
        now = time.time()
        count, oldest = self._count_in_window(key, limit.window_seconds, now)
        if count < limit.max_events or oldest is None:
            return 0
        return max(1, int(oldest + limit.window_seconds - now) + 1)

    async def window_record(self, key: str, window: int) -> None:
        self._windows[key].append(time.time())

    async def window_count(self, key: str, window: int) -> int:
        count, _ = self._count_in_window(key, window, time.time())
        return count

    async def window_clear(self, key: str) -> None:
        self._windows.pop(key, None)

    async def distinct_would_exceed(self, key: str, value: str, limit: Limit) -> int:
        now = time.time()
        bucket = self._prune_distinct(key, limit.window_seconds, now)
        if value in bucket or len(bucket) < limit.max_events:
            return 0
        oldest = min(bucket.values())
        return max(1, int(oldest + limit.window_seconds - now) + 1)

    async def distinct_record(self, key: str, value: str, window: int) -> None:
        self._distinct[key][value] = time.time()

    async def distinct_count(self, key: str, window: int) -> int:
        return len(self._prune_distinct(key, window, time.time()))

    async def close(self) -> None:
        return None


class RedisBackend:
    def __init__(self, client, prefix: str = "cb:quota:") -> None:
        self._redis = client
        self._prefix = prefix

    def _k(self, key: str) -> str:
        return f"{self._prefix}{key}"

    async def window_would_exceed(self, key: str, limit: Limit) -> int:
        now = time.time()
        rk = self._k(key)
        floor = now - limit.window_seconds
        pipe = self._redis.pipeline()
        pipe.zcount(rk, floor, "+inf")
        pipe.zrangebyscore(rk, floor, "+inf", start=0, num=1, withscores=True)
        count, oldest = await pipe.execute()

        if count < limit.max_events or not oldest:
            return 0
        oldest_score = float(oldest[0][1])
        return max(1, int(oldest_score + limit.window_seconds - now) + 1)

    async def window_record(self, key: str, window: int) -> None:
        now = time.time()
        rk = self._k(key)
        pipe = self._redis.pipeline()
        pipe.zadd(rk, {f"{now:.6f}:{uuid.uuid4().hex[:8]}": now})
        pipe.expire(rk, window + 60)
        await pipe.execute()

    async def window_count(self, key: str, window: int) -> int:
        now = time.time()
        return int(await self._redis.zcount(self._k(key), now - window, "+inf"))

    async def window_clear(self, key: str) -> None:
        await self._redis.delete(self._k(key))

    async def distinct_would_exceed(self, key: str, value: str, limit: Limit) -> int:
        now = time.time()
        rk = self._k(f"d:{key}")
        floor = now - limit.window_seconds
        pipe = self._redis.pipeline()
        pipe.zscore(rk, value)
        pipe.zcount(rk, floor, "+inf")
        pipe.zrangebyscore(rk, floor, "+inf", start=0, num=1, withscores=True)
        existing, count, oldest = await pipe.execute()

        if (existing is not None and existing >= floor) or count < limit.max_events:
            return 0
        if not oldest:
            return 0
        oldest_score = float(oldest[0][1])
        return max(1, int(oldest_score + limit.window_seconds - now) + 1)

    async def distinct_record(self, key: str, value: str, window: int) -> None:
        now = time.time()
        rk = self._k(f"d:{key}")
        pipe = self._redis.pipeline()
        pipe.zadd(rk, {value: now})
        pipe.expire(rk, window + 60)
        await pipe.execute()

    async def distinct_count(self, key: str, window: int) -> int:
        now = time.time()
        return int(await self._redis.zcount(self._k(f"d:{key}"), now - window, "+inf"))

    async def close(self) -> None:
        await self._redis.aclose()
