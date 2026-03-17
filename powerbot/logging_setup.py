"""Logging setup for PowerBot.

- Prefers **loguru** if installed (nice formatting, rotation).
- Falls back to stdlib `logging` if not.

This module is dependency-light so the bot still runs on minimal installs.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional


class DropReconnectNoiseFilter(logging.Filter):
    """Drop noisy transient Discord reconnect DNS stack traces from logs."""
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage() or ""
            if "Attempting a reconnect in" in msg:
                return False
            if "Cannot connect to host gateway" in msg and "discord.gg" in msg:
                return False
            if "ClientConnectorDNSError" in msg and "discord.gg" in msg:
                return False
        except Exception:
            return True
        return True



def _normalize_level(level: str) -> str:
    lvl = (level or "INFO").strip().upper()
    if lvl not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "TRACE"}:
        lvl = "INFO"
    return lvl


def setup_logging(log_path: Optional[str] = None, level: str = "INFO") -> None:
    """Initialize logging.

    If `loguru` is installed, logs are written to stdout and (optionally) to `log_path`
    with rotation.

    Otherwise, uses stdlib logging.
    """

    lvl = _normalize_level(level)

    # Prefer loguru if available
    try:
        from loguru import logger  # type: ignore

        try:
            logging.getLogger().addFilter(DropReconnectNoiseFilter())
        except Exception:
            pass


        # Remove default handlers to avoid duplicate logs
        logger.remove()

        # Console
        logger.add(lambda msg: print(msg, end=""), level=lvl, colorize=True, backtrace=False, diagnose=False)

        # File
        if log_path:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            logger.add(
                log_path,
                level=lvl,
                rotation="5 MB",
                retention="14 days",
                encoding="utf-8",
                backtrace=False,
                diagnose=False,
            )

        # Bridge stdlib logging -> loguru
        class _InterceptHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                try:
                    level_name = logger.level(record.levelname).name
                except Exception:
                    level_name = record.levelname
                logger.opt(depth=6, exception=record.exc_info).log(level_name, record.getMessage())

        logging.root.handlers = [_InterceptHandler()]
        logging.root.setLevel(logging.DEBUG)
        for name in ["discord", "discord.http", "discord.client", "asyncio"]:
            logging.getLogger(name).handlers = [_InterceptHandler()]
            logging.getLogger(name).propagate = False

        logger.debug("[PowerBot] Logging initialized (loguru).")
        return
    except Exception:
        # Fall back to stdlib logging
        pass

    try:
        logging.getLogger().addFilter(DropReconnectNoiseFilter())
    except Exception:
        pass

    logging.basicConfig(level=getattr(logging, lvl, logging.INFO), format="[%(levelname)s] %(name)s: %(message)s")
    logging.getLogger(__name__).debug("[PowerBot] Logging initialized (stdlib).")