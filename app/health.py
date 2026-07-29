"""Heartbeat-файл для HEALTHCHECK."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)


async def heartbeat_loop(path: Path, interval: int) -> None:
    while True:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
            os.utime(path, None)
        except OSError as exc:
            logger.warning("Не удалось обновить heartbeat-файл: %s", exc)
        await asyncio.sleep(interval)


def check(path: Path, max_age: int) -> int:
    """Точка входа для HEALTHCHECK: возвращает код выхода."""
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        print("heartbeat-файл отсутствует", file=sys.stderr)
        return 1
    if age > max_age:
        print(f"heartbeat устарел на {age:.0f} с", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    heartbeat_path = Path(os.getenv("HEALTHCHECK_FILE", "/tmp/bot-healthy"))
    interval = int(os.getenv("HEARTBEAT_INTERVAL", "30"))
    sys.exit(check(heartbeat_path, max_age=interval * 3))
