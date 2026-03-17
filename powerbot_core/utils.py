from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_read_json(path: str | Path, default: Any) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def safe_write_json(path: str | Path, data: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def slugify(text: str) -> str:
    text = normalize_spaces(text).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "item"


def try_parse_date(text: str | None) -> date | None:
    if not text:
        return None
    raw = normalize_spaces(str(text)).replace(".", "-").replace("/", "-")
    today = date.today()
    fmts = ["%Y-%m-%d", "%m-%d-%Y", "%m-%d-%y", "%b %d %Y", "%B %d %Y"]
    for fmt in fmts:
        try:
            return datetime.strptime(raw, fmt).date()
        except Exception:
            continue

    m = re.fullmatch(r"([A-Za-z]+) (\d{1,2})", raw)
    if m:
        month_name = m.group(1)
        day_num = int(m.group(2))
        try:
            parsed = datetime.strptime(f"{month_name} {day_num} {today.year}", "%B %d %Y").date()
        except Exception:
            try:
                parsed = datetime.strptime(f"{month_name} {day_num} {today.year}", "%b %d %Y").date()
            except Exception:
                parsed = None
        if parsed:
            return parsed

    return None


def relative_due_date(text: str | None) -> date | None:
    low = normalize_spaces(str(text or "").lower())
    if not low:
        return None
    today = date.today()
    if "today" in low:
        return today
    if "tomorrow" in low:
        return today + timedelta(days=1)
    if "this week" in low or "by week end" in low or "weekend" in low:
        return today + timedelta(days=max(0, 6 - today.weekday()))
    if "next week" in low:
        end_this_week = today + timedelta(days=max(0, 6 - today.weekday()))
        return end_this_week + timedelta(days=7)
    m = re.search(r"(?:by )?([A-Za-z]+day)$", low) or re.search(r"by ([A-Za-z]+day)", low)
    if m:
        day_name = m.group(1)
        day_to_num = {
            "monday": 0,
            "tuesday": 1,
            "wednesday": 2,
            "thursday": 3,
            "friday": 4,
            "saturday": 5,
            "sunday": 6,
        }
        target = day_to_num.get(day_name)
        if target is not None:
            delta = (target - today.weekday()) % 7
            days = delta
            if "next " in low and days == 0:
                days = 7
            return today + timedelta(days=days)
    return None


def clip(text: str, max_len: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def title_case_safe(text: str | None) -> str:
    return normalize_spaces(str(text or "")).title()


def text_score(query: str, hay: str) -> int:
    query_words = [w for w in normalize_spaces(query).lower().split() if len(w) >= 3]
    hay_low = (hay or "").lower()
    score = 0
    for word in query_words:
        if word in hay_low:
            score += 1
    normalized_query = normalize_spaces(query).lower()
    if normalized_query and normalized_query in hay_low:
        score += 2
    return score
