"""Настройка логирования."""

from __future__ import annotations

import logging
import logging.handlers
import sys

from .config import Settings

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(settings: Settings) -> logging.Logger:
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    root.addHandler(stream)

    if settings.log_to_file:
        try:
            settings.log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                settings.log_dir / "bot.log",
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError as exc:
            root.addHandler(stream)
            logging.getLogger(__name__).warning(
                "Не удалось включить файловое логирование: %s", exc
            )

    root.setLevel(settings.log_level if settings.log_level in logging._nameToLevel else "INFO")

    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("asyncssh").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)

    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    return logging.getLogger("crypto-bot")
