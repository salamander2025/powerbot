"""Async job scheduling for PowerBot (APScheduler).

Optional: if APScheduler isn't installed, everything safely no-ops.
"""

from __future__ import annotations

from typing import Any, Callable, Optional


def try_create_scheduler() -> Optional[Any]:
    """Return an AsyncIOScheduler instance, or None if APScheduler isn't installed."""
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore
        return AsyncIOScheduler()
    except Exception:
        return None


def safe_add_weekly_job(
    scheduler: Any,
    *,
    func: Callable[[], Any],
    weekday: int,
    hour: int,
    minute: int = 0,
    job_id: str = "weekly_digest",
) -> bool:
    """Add a weekly job if scheduler exists. weekday: 0=Monday .. 6=Sunday"""
    if not scheduler:
        return False
    try:
        scheduler.add_job(
            func,
            trigger="cron",
            day_of_week=int(weekday),
            hour=int(hour),
            minute=int(minute),
            id=job_id,
            replace_existing=True,
        )
        return True
    except Exception:
        return False
