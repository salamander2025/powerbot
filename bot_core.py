from __future__ import annotations


import os
import json
import csv
import copy
import math
from datetime import datetime, timedelta, date, timezone
from pathlib import Path

import random
import shutil
import re

import traceback
import uuid
import asyncio
import logging

import discord
from discord.ext import commands, tasks


from dotenv import load_dotenv
from typing import Optional, Dict, Tuple, Any, List

# PowerBot modular helpers (optional deps are handled internally)
from powerbot.logging_setup import setup_logging
from powerbot.storage import read_json, write_json, append_json_list
from powerbot.db import PowerBotDB
from powerbot.semantic import build_index, query_index
from powerbot.scheduler import try_create_scheduler, safe_add_weekly_job
from powerbot.validation import validate, CONFIG_SCHEMA
from powerbot_core import PowerBotHubService

# ---------------- OWNER CONFIG (override via env for public/starter deployments) ----------------
def _owner_id_from_env() -> int:
    raw = os.getenv("POWERBOT_OWNER_ID", "0").strip()
    try:
        return int(raw)
    except ValueError:
        return 0

def _owner_role_id_from_env() -> int:
    raw = os.getenv("POWERBOT_OWNER_ROLE_ID", "0").strip()
    try:
        return int(raw)
    except ValueError:
        return 0


def _vp_role_id_from_env() -> int:
    raw = os.getenv("POWERBOT_VP_ROLE_ID", "0").strip()
    try:
        return int(raw)
    except ValueError:
        return 0


OWNER_ID = _owner_id_from_env()
OWNER_ROLE_ID = _owner_role_id_from_env()
VP_ROLE_ID = _vp_role_id_from_env()
# Load .env so DISCORD_TOKEN is available
load_dotenv()
# Also try loading a .env next to this file (helps when launched from a different working dir)
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'), override=False)


# ---------------- EBOARD ARCHIVE HELPER ----------------

# Uses the shared storage helper to prevent JSON corruption.

def append_eboard_archive(entry: dict):
    try:
        append_json_list(EBOARD_ARCHIVE_PATH, entry, schema='powerbot.eboard_archive.v1')
    except Exception as e:
        print(f"[PowerBot] Failed to append eboard archive: {e}")


# ---------------- AI ADVISOR CONFIG ----------------
# No-key AI backend: local Ollama (recommended). If unavailable, PowerBot falls back
# to its built-in rule-based advisor and the bot still runs.
AI_BACKEND = os.getenv("AI_BACKEND", "ollama").strip().lower()  # ollama | none
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").strip().rstrip("/")
AI_MODEL = (os.getenv("AI_MODEL", "") or os.getenv("OLLAMA_MODEL", "llama3.1")).strip()
AI_MAX_TOKENS = int(os.getenv("AI_MAX_TOKENS", "450"))
AI_COOLDOWN_SECONDS = int(os.getenv("AI_COOLDOWN_SECONDS", "8"))


# ---------------- BASIC CONFIG ---------------- #

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

VERSION_PATH = os.path.join(BASE_DIR, "VERSION")

def _read_text_file(path: str, default: str = "") -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return (f.read() or "").strip()
    except Exception:
        return default

POWERBOT_VERSION = _read_text_file(VERSION_PATH, "") or ""

DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
EVENTS_PATH = os.path.join(DATA_DIR, "events.json")
TASKS_PATH = os.path.join(DATA_DIR, "tasks.json")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
EBOARD_LOG_PATH = os.path.join(DATA_DIR, "eboard_talk_log.txt")
EBOARD_ARCHIVE_PATH = os.path.join(DATA_DIR, "knowledge", "eboard_talk_archive.json")

# ---------------- OPTIONAL MEMORY ARCHIVES ----------------
GEN_CHAT_ARCHIVE_PATH = os.path.join(DATA_DIR, "knowledge", "gen_chat_archive.json")
# ---------------- KNOWLEDGE FILE PATHS (JSON) ----------------
KNOWLEDGE_DIR = os.path.join(DATA_DIR, "knowledge")

CLUB_MEMORY_JSON_PATH = os.path.join(KNOWLEDGE_DIR, "club_memory.json")
CAMPUS_MEMORY_JSON_PATH = os.path.join(KNOWLEDGE_DIR, "campus_memory.json")
QA_RULES_JSON_PATH = os.path.join(KNOWLEDGE_DIR, "qa_rules.json")
TONE_JSON_PATH = os.path.join(KNOWLEDGE_DIR, "tone.json")
SCHEDULES_JSON_PATH = os.path.join(KNOWLEDGE_DIR, "schedules.json")
PLANNING_NOTES_JSON_PATH = os.path.join(KNOWLEDGE_DIR, "planning_notes.json")
COMPILED_RULES_PATH = os.path.join(KNOWLEDGE_DIR, "compiled_rules.json")



# ---------------- LOGGING ----------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_PATH = os.path.join(DATA_DIR, "powerbot.log")
setup_logging(LOG_PATH, LOG_LEVEL)
logger = logging.getLogger("powerbot")

# ---------------- OPTIONAL EXTRAS PATHS ----------------
SEMANTIC_INDEX_DIR = os.path.join(DATA_DIR, "semantic")
DB_PATH = os.path.join(DATA_DIR, "powerbot.db")
_PB_DB: PowerBotDB | None = None
_PB_SCHEDULER = None
PB_HUB: PowerBotHubService | None = None


# ---------------- SAFE CONFIG (PERSISTENT SETTINGS) ---------------- #

def _read_json_file(path: str, default: Any = None) -> Any:
    """Read JSON safely; never crash if missing/corrupt.

    Self-repair behavior:
      - If JSON is corrupt, rename it to `<name>.corrupt.<timestamp>`
      - If `default` is provided, write `default` back to the original path
      - Return parsed JSON (or `default` / {} on error)
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        if default is None:
            return {}
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except Exception:
            pass
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
        return default
    except Exception:
        # Corrupt JSON: quarantine + repair
        try:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            base_name = os.path.basename(path)
            dir_name = os.path.dirname(path)
            corrupt_name = os.path.join(dir_name, f"{base_name}.corrupt.{ts}")
            try:
                os.replace(path, corrupt_name)
            except Exception:
                pass
        except Exception:
            pass

        if default is None:
            return {}

        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except Exception:
            pass
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
        return default





def _search_snippet_archive(path: str, query: str, limit: int = 2) -> list[str]:
    """Lightweight keyword search for snippet-style archives (no ML, no downloads)."""
    q = (query or "").lower().strip()
    if not q:
        return []
    try:
        data = _read_json_file(path, {})
        msgs = data.get("messages") if isinstance(data, dict) else None
        if not isinstance(msgs, list):
            return []
        words = [w for w in re.split(r"\W+", q) if w]
        scored = []
        for m in msgs:
            if not isinstance(m, dict):
                continue
            content = str(m.get("content") or "")
            c = content.lower()
            score = sum(1 for w in words if w in c)
            if score >= 2 or (len(words) == 1 and words[0] in c):
                author = m.get("author") or "unknown"
                ts = str(m.get("timestamp") or "")[:10]
                snippet = content.replace("\n", " ").strip()
                if len(snippet) > 160:
                    snippet = snippet[:160] + "…"
                scored.append((score, f"- {ts} {author}: {snippet}"))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:limit]]
    except Exception:
        return []


def _write_json_file(path: str, data: dict) -> None:
    """Best-effort JSON writer. Never raises, and writes atomically to avoid corruption."""
    try:
        dirpath = os.path.dirname(path) or "."
        os.makedirs(dirpath, exist_ok=True)

        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        # Atomic replace on both Windows + POSIX
        os.replace(tmp_path, path)
    except Exception:
        # never hard-crash the bot over config saves
        try:
            # best-effort cleanup
            tmp_path = f"{path}.tmp"
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

# Global "AI master switch" (controls ALL AI usage: chat + AI-powered ops helpers)
_AI_CONFIG_KEY = "ai_enabled"

# Load persistent config once at startup (can be reloaded via helper functions)
config: dict = _read_json_file(CONFIG_PATH, {})
try:
    ok, errors = validate(CONFIG_SCHEMA, config)
    if not ok and errors:
        print(f"[PowerBot] config.json validation warnings: {errors}")
except Exception:
    pass
try:
    from powerbot_core.config_validation import validate_config_object
    _cfg_report = validate_config_object(config)
    for issue in _cfg_report.errors:
        logger.error("[config] %s: %s", issue.key, issue.message)
    for issue in _cfg_report.warnings:
        logger.warning("[config] %s: %s", issue.key, issue.message)
except Exception:
    pass

_config_cache = config  # backward compatible alias
AI_ENABLED: bool = bool(config.get(_AI_CONFIG_KEY, False))
AI_AUTO_ENABLE: bool = bool(config.get("ai_auto_enable", True))
print(f"[AI SWITCH] AI_ENABLED={AI_ENABLED}")




_CONFIG_MTIME: float | None = None




def _analytics_dir() -> str:
    try:
        p = os.path.join(DATA_DIR, "analytics")
        os.makedirs(p, exist_ok=True)
        return p
    except Exception:
        return os.path.join(DATA_DIR, "analytics")


def compute_learned_patterns(events: list[dict]) -> dict:
    """
    Learn lightweight patterns from stored events (no ML deps).
    Output is safe and bounded; designed to nudge forecasts, not override them.
    """
    # Extract dated attendance
    rows = []
    for e in events:
        if not isinstance(e, dict):
            continue
        att = e.get("attendance", 0)
        if not isinstance(att, (int, float)) or att <= 0:
            continue
        d = _parse_event_date_guess(e)
        et = str(e.get("event_type", "unknown")).lower().strip()
        tags = e.get("tags") if isinstance(e.get("tags"), list) else []
        def _has(flag: str) -> bool:
            return bool(e.get(flag)) or (flag in tags)

        rows.append({
            "date": d,
            "weekday": d.weekday() if d else None,
            "event_type": et,
            "attendance": float(att),
            "food": _has("food") or _has("has_food"),
            "prizes": _has("prizes") or _has("has_prizes"),
            "collab": _has("collab") or _has("collaboration") or _has("is_collab"),
            "strong_promo": _has("strong_promo") or _has("full_promo") or _has("marketing_full"),
        })

    if len(rows) < 4:
        return {"meta": {"events_used": len(rows)}, "type_uplift": {}, "weekday_uplift": {}, "signals": {}}

    overall = [r["attendance"] for r in rows]
    overall_avg = sum(overall) / len(overall)

    # Type uplift
    type_uplift = {}
    by_type = {}
    for r in rows:
        by_type.setdefault(r["event_type"], []).append(r["attendance"])
    for et, vals in by_type.items():
        if len(vals) < 2:
            continue
        avg = sum(vals) / len(vals)
        raw = (avg / overall_avg) if overall_avg > 0 else 1.0
        type_uplift[et] = max(0.70, min(1.50, raw))

    # Weekday uplift
    weekday_uplift = {}
    by_wd = {}
    for r in rows:
        wd = r["weekday"]
        if wd is None:
            continue
        by_wd.setdefault(wd, []).append(r["attendance"])
    for wd, vals in by_wd.items():
        if len(vals) < 2:
            continue
        avg = sum(vals) / len(vals)
        raw = (avg / overall_avg) if overall_avg > 0 else 1.0
        weekday_uplift[str(wd)] = max(0.90, min(1.10, raw))

    # Simple signal effects (food/prizes/collab/strong promo)
    def effect(flag: str) -> float | None:
        a = [r["attendance"] for r in rows if r.get(flag)]
        b = [r["attendance"] for r in rows if not r.get(flag)]
        if len(a) < 2 or len(b) < 2:
            return None
        ma = sum(a)/len(a)
        mb = sum(b)/len(b)
        if mb <= 0:
            return None
        raw = ma/mb
        return max(0.85, min(1.20, raw))

    signals = {}
    for flag in ["food", "prizes", "collab", "strong_promo"]:
        v = effect(flag)
        if v is not None:
            signals[flag] = v

    return {
        "meta": {
            "events_used": len(rows),
            "overall_avg": overall_avg,
            "updated_utc": datetime.now(timezone.utc).isoformat(),
        },
        "type_uplift": type_uplift,
        "weekday_uplift": weekday_uplift,
        "signals": signals,
    }


def load_learned_patterns() -> dict:
    try:
        path = os.path.join(_analytics_dir(), "learned_patterns.json")
        data = _read_json_file(path, {})
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def update_learned_patterns(force: bool = False) -> dict:
    """
    Recompute learned patterns at most once per day (or when forced).
    """
    try:
        path = os.path.join(_analytics_dir(), "learned_patterns.json")
        if not force and os.path.exists(path):
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
                if (datetime.now(timezone.utc) - mtime).total_seconds() < 24 * 3600:
                    data = _read_json_file(path, {})
                    return data if isinstance(data, dict) else {}
            except Exception:
                pass

        events = load_events()
        learned = compute_learned_patterns(events)
        _write_json_file(path, learned)
        return learned
    except Exception:
        return {}


def get_config() -> dict:
    """Return config.json with simple mtime-based caching."""
    global config, _config_cache, AI_ENABLED, _CONFIG_MTIME
    try:
        mtime = os.path.getmtime(CONFIG_PATH)
    except Exception:
        return config if isinstance(config, dict) else {}
    if _CONFIG_MTIME is not None and mtime == _CONFIG_MTIME and isinstance(config, dict):
        return config
    config = _read_json_file(CONFIG_PATH, {})
    _config_cache = config
    AI_ENABLED = bool(config.get(_AI_CONFIG_KEY, False))
    _CONFIG_MTIME = mtime
    return config

def load_config() -> dict:
    return get_config()


def save_config(cfg: dict) -> None:
    """Persist config + keep AI_ENABLED in sync. Never raises."""
    global config, _config_cache, AI_ENABLED, _CONFIG_MTIME
    try:
        cfg = dict(cfg) if isinstance(cfg, dict) else {}
        cfg.setdefault("last_updated", date.today().isoformat())
        _write_json_file(CONFIG_PATH, cfg)
        try:
            _CONFIG_MTIME = os.path.getmtime(CONFIG_PATH)
        except Exception:
            pass
        config = cfg
        _config_cache = config
        AI_ENABLED = bool(config.get(_AI_CONFIG_KEY, False))
    except Exception:
        return


# Events helpers (events.json is a LIST of event dicts)
def load_events() -> list[dict]:
    data = read_json(EVENTS_PATH, [])
    if isinstance(data, list):
        return [e for e in data if isinstance(e, dict)]
    # Backward compat: allow {"events": [...]}
    if isinstance(data, dict) and isinstance(data.get("events"), list):
        return [e for e in data["events"] if isinstance(e, dict)]
    return []


def save_events(events: list[dict]) -> None:
    try:
        write_json(EVENTS_PATH, list(events))
    except Exception:
        return

def _parse_event_date_guess(event: dict) -> date | None:
    """Best-effort event date parser for stored event rows."""
    if not isinstance(event, dict):
        return None
    for key in ("date", "timestamp", "created_at"):
        raw = event.get(key)
        if not raw:
            continue
        try:
            s = str(raw).strip()
            if len(s) == 10 and s[4] == '-' and s[7] == '-':
                return datetime.strptime(s, "%Y-%m-%d").date()
            if s.endswith('Z'):
                s = s[:-1] + '+00:00'
            return datetime.fromisoformat(s).date()
        except Exception:
            continue
    return None


def _load_eboard_archive_messages() -> list[dict]:
    """Load archived e-board messages from the JSON archive."""
    data = _read_json_file(EBOARD_ARCHIVE_PATH, {"messages": []})
    msgs = data.get("messages") if isinstance(data, dict) else data
    if not isinstance(msgs, list):
        return []
    return [m for m in msgs if isinstance(m, dict)]


def _club_context_snippet() -> str:
    club = KNOWLEDGE.get("club", {}) if isinstance(KNOWLEDGE, dict) else {}
    meeting = club.get("meeting") if isinstance(club.get("meeting"), dict) else {}
    lines = [
        f"Club: {club.get('club_name', 'Your Club')}",
        f"University: {club.get('university', 'Your University')}",
        f"Meeting: {meeting.get('day', club.get('meeting_day', 'Monday'))} {meeting.get('time', club.get('meeting_time', MEETING_TIME))} @ {meeting.get('room', club.get('meeting_room', MEETING_ROOM))}",
    ]
    event_types = club.get("event_types") if isinstance(club.get("event_types"), list) else []
    if event_types:
        lines.append("Known event types: " + ", ".join(str(x) for x in event_types[:10]))
    return "\n".join(lines)


def record_followup(channel_id: int, user_id: int, message_id: int | None = None) -> None:
    """Backwards-compatible no-op follow-up tracker used by legacy public QA paths."""
    try:
        _ai_followups[int(user_id)] = (_now_ts() + FOLLOWUP_WINDOW_SECONDS, int(channel_id))
    except Exception:
        return


def build_private_consult_context(source: str) -> str:
    """Compatibility wrapper for older DM AI path."""
    try:
        return _build_consult_context(source, session_id=_private_consult_session_id())
    except Exception:
        return _club_context_snippet()


def _append_event_plan_log(entry: dict) -> None:
    try:
        append_json_list(os.path.join(DATA_DIR, "event_plan_log.json"), entry, schema="powerbot.event_plan_log.v1")
    except Exception:
        return


def _context_multiplier_from_text(text: str) -> tuple[float, list[str]]:
    t = (text or "").lower()
    mult = 1.0
    reasons: list[str] = []
    if any(k in t for k in ["food", "snack", "ramen", "pizza", "kfc", "boba"]):
        mult *= 1.12
        reasons.append("food")
    if any(k in t for k in ["prize", "raffle", "giveaway"]):
        mult *= 1.06
        reasons.append("prizes")
    if any(k in t for k in ["collab", "cohost", "cosponsor", "co-sponsor", "partner"]):
        mult *= 1.10
        reasons.append("collab")
    if any(k in t for k in ["instagram", "flyer", "countdown", "engage", "discord ping", "story"]):
        mult *= 1.08
        reasons.append("strong_promo")
    if any(k in t for k in ["rain", "storm", "snow"]):
        mult *= 0.92
        reasons.append("bad_weather")
    if any(k in t for k in ["final", "finals"]):
        mult *= 0.82
        reasons.append("finals")
    if any(k in t for k in ["midterm", "exam week"]):
        mult *= 0.90
        reasons.append("midterms")
    return max(0.65, min(mult, 1.45)), reasons


def smart_forecast_3(event_type: str, the_date: date | None = None, context_text: str | None = None) -> dict:
    """Fast, dependency-light attendance forecast used across planning commands."""
    cfg = get_config()
    events = load_events()
    valid = [e for e in events if isinstance(e, dict) and isinstance(e.get("attendance"), (int, float)) and float(e.get("attendance") or 0) > 0]

    base_default = float(cfg.get("base_attendance") or CLUB_MEMORY.get("baseline_attendance_default", 15) or 15)
    overall_avg = (sum(float(e.get("attendance") or 0) for e in valid) / len(valid)) if valid else base_default

    et = (event_type or "other").strip().lower() or "other"
    type_rows = [e for e in valid if str(e.get("event_type", "")).strip().lower() == et]
    type_avg = (sum(float(e.get("attendance") or 0) for e in type_rows) / len(type_rows)) if type_rows else overall_avg

    learned = load_learned_patterns() or update_learned_patterns(force=False)
    type_uplift = 1.0
    weekday_uplift = 1.0
    learned_signal_mult = 1.0
    if isinstance(learned, dict):
        try:
            type_uplift = float((learned.get("type_uplift") or {}).get(et, 1.0) or 1.0)
        except Exception:
            type_uplift = 1.0
        if the_date is not None:
            try:
                weekday_uplift = float((learned.get("weekday_uplift") or {}).get(str(the_date.weekday()), 1.0) or 1.0)
            except Exception:
                weekday_uplift = 1.0

    mult_event = float(((cfg.get("multipliers") or {}).get("event_type") or {}).get(et, EVENT_TYPE_MULTIPLIERS.get(et, 1.0)) or 1.0)
    mult_history = max(0.80, min(type_avg / max(overall_avg, 1.0), 1.30))

    acad = get_academic_context(the_date) if isinstance(the_date, date) else {"multiplier": 1.0, "phase": "Unknown", "term": "Unknown", "notes": []}
    mult_calendar = float(acad.get("multiplier", 1.0) or 1.0)

    mult_context, ctx_reasons = _context_multiplier_from_text(context_text or "")

    for reason in ctx_reasons:
        key = "strong_promo" if reason == "strong_promo" else reason
        try:
            learned_signal_mult *= float((learned.get("signals") or {}).get(key, 1.0) or 1.0)
        except Exception:
            continue
    learned_signal_mult = max(0.85, min(learned_signal_mult, 1.25))

    mult_marketing = 1.08 if "strong_promo" in ctx_reasons else 1.0
    if mult_marketing != 1.0 and mult_context >= 1.08:
        mult_context = max(1.0, mult_context / 1.08)

    mult_fatigue = 1.0
    recent_sorted = sorted(valid, key=lambda e: str(e.get("date") or e.get("timestamp") or e.get("created_at") or ""))
    recent_same = [e for e in recent_sorted[-4:] if str(e.get("event_type", "")).strip().lower() == et]
    if len(recent_same) >= 2:
        mult_fatigue = 0.93

    base = max(base_default, min(overall_avg, base_default * 1.20))
    expected = base * mult_event * mult_history * type_uplift * weekday_uplift * mult_calendar * mult_fatigue * mult_marketing * mult_context * learned_signal_mult

    member_cap = float(cfg.get("total_members") or CLUB_MEMORY.get("model_members_default", 50) or 50)
    expected = max(2.0, min(expected, member_cap))

    spread = max(2.0, expected ** 0.5 * 1.35)
    low = max(0.0, expected - spread)
    high = min(member_cap, expected + spread)
    under_prob = 0.55 if expected < base_default * 0.9 else (0.30 if expected < base_default else 0.12)

    return {
        "event_type": et,
        "expected": float(expected),
        "low": float(low),
        "high": float(high),
        "base": float(base),
        "n": int(member_cap),
        "type_avg": float(type_avg),
        "overall_avg": float(overall_avg),
        "mult_event": float(mult_event),
        "mult_history": float(mult_history),
        "mult_learned": float(type_uplift * learned_signal_mult),
        "mult_weekday": float(weekday_uplift),
        "mult_calendar": float(mult_calendar),
        "mult_fatigue": float(mult_fatigue),
        "mult_marketing": float(mult_marketing),
        "mult_context": float(mult_context),
        "under_prob": float(max(0.02, min(under_prob, 0.98))),
        "acad_info": acad,
        "context_reasons": ctx_reasons,
    }


def attendance_forecast(event_type: str, context_text: str | None = None, *, the_date: date | None = None) -> dict:
    res = smart_forecast_3(event_type, the_date, context_text)
    return {
        **res,
        "low_90": int(round(res.get("low", 0))),
        "high_90": int(round(res.get("high", 0))),
    }


def _find_event_by_query(events: list[dict], query: str) -> dict | None:
    q = (query or "").strip().lower()
    if not q:
        return events[-1] if events else None
    for e in events:
        try:
            if str(e.get("id", "")).lower() == q:
                return e
        except Exception:
            continue
    scored: list[tuple[int, dict]] = []
    words = [w for w in re.findall(r"[a-z0-9']+", q) if w]
    for e in events:
        hay = " ".join([
            str(e.get("name") or ""),
            str(e.get("title") or ""),
            str(e.get("event_type") or ""),
            str(e.get("notes") or ""),
            str(e.get("date") or e.get("timestamp") or ""),
        ]).lower()
        score = 0
        if q and q in hay:
            score += 8
        score += sum(2 for w in words if w in hay)
        if score:
            scored.append((score, e))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1] if scored else None


def _event_cost_value(event: dict, db: PowerBotDB | None) -> float | None:
    if not isinstance(event, dict) or not db:
        return None
    eid = event.get("id")
    if eid is None:
        return None
    try:
        return float(db.sum_expenses_for_event(int(eid)) or 0)
    except Exception:
        return None


def _event_success_score(event: dict, db: PowerBotDB | None) -> dict:
    name = str(event.get("name") or event.get("title") or event.get("event_type") or f"event #{event.get('id', '?')}")
    attendance = float(event.get("attendance") or 0)
    dt = _parse_event_date_guess(event)
    forecast = smart_forecast_3(str(event.get("event_type") or "other"), dt, str(event.get("notes") or ""))
    expected = float(forecast.get("expected") or 0)
    delta_pct = ((attendance - expected) / expected) if expected > 0 else None
    cost = _event_cost_value(event, db)
    cpa = (float(cost) / attendance) if isinstance(cost, (int, float)) and attendance > 0 else None
    success = 5.0
    if delta_pct is not None:
        success += max(-3.0, min(delta_pct * 6.0, 3.0))
    if cpa is not None:
        success += 1.0 if cpa <= 3 else (0.4 if cpa <= 5 else (-0.8 if cpa >= 9 else 0.0))
    success = max(1.0, min(success, 10.0))
    return {
        "id": event.get("id"),
        "name": name,
        "event_type": str(event.get("event_type") or "other").lower(),
        "attendance": attendance,
        "expected": expected,
        "delta_pct": delta_pct,
        "cost": cost,
        "cost_per_attendee": cpa,
        "success_score": success,
    }


def _momentum_metrics(events: list[dict]) -> dict:
    rows = [float(e.get("attendance") or 0) for e in events if isinstance(e.get("attendance"), (int, float)) and float(e.get("attendance") or 0) > 0]
    if len(rows) < 4:
        return {"available": False, "recent": rows[-4:]}
    recent = rows[-3:]
    prev = rows[-6:-3] if len(rows) >= 6 else rows[:-3]
    prev_avg = (sum(prev) / len(prev)) if prev else None
    recent_avg = sum(recent) / len(recent)
    growth = ((recent_avg - prev_avg) / prev_avg * 100.0) if prev_avg and prev_avg > 0 else None
    return {
        "available": True,
        "recent": [int(x) for x in recent],
        "growth_pct": growth,
        "projected_next": recent_avg,
    }


def _diversity_metrics(events: list[dict]) -> dict:
    types = [str(e.get("event_type") or "other").lower() for e in events[-6:] if isinstance(e, dict)]
    if not types:
        return {"available": False}
    unique = len(set(types))
    score = "High" if unique >= 4 else ("Medium" if unique >= 3 else "Low")
    most = max(set(types), key=types.count) if types else None
    return {"available": True, "variety_score": score, "most_repeated": most, "unique_recent": unique}


def _retention_metrics(events: list[dict]) -> dict:
    seen: set[str] = set()
    returning = 0
    new = 0
    for e in events[-10:]:
        roster = e.get("participants") or e.get("attendees") or e.get("roster") or []
        if not isinstance(roster, list):
            continue
        for raw in roster:
            key = str(raw).strip().lower()
            if not key:
                continue
            if key in seen:
                returning += 1
            else:
                seen.add(key)
                new += 1
    total = returning + new
    if total == 0:
        return {"available": False}
    return {"available": True, "returning": returning, "new": new, "retention_rate": (returning / total) * 100.0}


def _marketing_metrics(events: list[dict]) -> dict:
    hi: list[float] = []
    lo: list[float] = []
    mid: list[float] = []
    for e in events:
        att = e.get("attendance")
        if not isinstance(att, (int, float)) or float(att) <= 0:
            continue
        strength = str(e.get("promo_strength") or "").lower()
        channels = e.get("promotion_channels") or []
        channel_count = len(channels) if isinstance(channels, list) else 0
        if strength in {"high", "strong", "full"} or channel_count >= 3:
            hi.append(float(att))
        elif strength in {"mid", "medium"} or channel_count == 2:
            mid.append(float(att))
        else:
            lo.append(float(att))
    if len(hi) + len(mid) + len(lo) < 3 or not lo:
        return {"available": False}
    base = sum(lo) / len(lo)
    out = {"available": True}
    if hi:
        out["high_uplift_pct"] = ((sum(hi) / len(hi)) - base) / base * 100.0 if base > 0 else 0.0
    if mid:
        out["mid_uplift_pct"] = ((sum(mid) / len(mid)) - base) / base * 100.0 if base > 0 else 0.0
    return out


def _collab_metrics(events: list[dict]) -> dict:
    collab: list[float] = []
    solo: list[float] = []
    for e in events:
        att = e.get("attendance")
        if not isinstance(att, (int, float)) or float(att) <= 0:
            continue
        tags = e.get("tags") if isinstance(e.get("tags"), list) else []
        is_collab = bool(e.get("collab") or e.get("is_collab") or "collab" in tags or e.get("partner_club"))
        (collab if is_collab else solo).append(float(att))
    if len(collab) < 1 or len(solo) < 1:
        return {"available": False}
    c = sum(collab) / len(collab)
    s = sum(solo) / len(solo)
    uplift = ((c - s) / s * 100.0) if s > 0 else 0.0
    return {"available": True, "uplift_pct": uplift}


def _budget_plan_metrics(events: list[dict], cfg: dict, db: PowerBotDB | None) -> dict:
    by_type: dict[str, list[float]] = {}
    if db:
        for e in events:
            cost = _event_cost_value(e, db)
            if not isinstance(cost, (int, float)) or cost <= 0:
                continue
            et = str(e.get("event_type") or "other").lower()
            by_type.setdefault(et, []).append(float(cost))
    return {
        "avg_cost_by_type": {k: (sum(v) / len(v)) for k, v in by_type.items() if v},
        "budget_total": float(cfg.get("budget_total") or 0),
    }

# DB helpers



# ---------------- BACKUPS ---------------- #

def _safe_backup_file(path: str, prefix: str, keep: int = 5) -> None:
    """Copy a file into BACKUP_DIR with timestamp and keep only the newest N backups.

    This is intentionally best-effort and completely silent on errors so that
    backups never break bot startup.
    """
    try:
        if not path or not os.path.exists(path):
            return
        Path(BACKUP_DIR).mkdir(parents=True, exist_ok=True)
        src = Path(path)
        if not src.is_file():
            return
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dest = Path(BACKUP_DIR) / f"{prefix}_{ts}{src.suffix}"
        shutil.copy2(src, dest)
        # Rotate old backups
        backups = sorted(
            Path(BACKUP_DIR).glob(f"{prefix}_*{src.suffix}"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in backups[keep:]:
            try:
                old.unlink()
            except Exception:
                pass
    except Exception:
        return


def perform_startup_backups() -> None:
    """Best-effort snapshot of critical data files on startup."""
    # Database
    try:
        _safe_backup_file(DB_PATH, "powerbot_db", keep=5)
    except Exception:
        pass
    # Core JSON configs
    for path, prefix in [
        (CONFIG_PATH, "config_json"),
        (EVENTS_PATH, "events_json"),
        (CLUB_MEMORY_JSON_PATH, "club_memory_json"),
        (CAMPUS_MEMORY_JSON_PATH, "campus_memory_json"),
        (QA_RULES_JSON_PATH, "qa_rules_json"),
        (SCHEDULES_JSON_PATH, "schedules_json"),
    ]:
        try:
            _safe_backup_file(path, prefix, keep=5)
        except Exception:
            continue

def init_db() -> None:
    global _PB_DB
    if _PB_DB is None:
        try:
            _PB_DB = PowerBotDB(DB_PATH)
        except Exception:
            _PB_DB = None

def get_db() -> PowerBotDB | None:
    return _PB_DB


def log_qa_interaction(*, guild_id, channel_id, user_id, user_name, question, answer, trace: dict, used_ai: bool = False):
    db = get_db()
    if not db:
        return
    try:
        used_rule = (trace.get("used") == "OFFICIAL_RULES")
        used_semantic = (trace.get("used") == "SEMANTIC")
        db.log_interaction(guild_id=guild_id, channel_id=channel_id, user_id=user_id, user_name=user_name, question=question, answer=answer, used_rule=used_rule, used_semantic=used_semantic, used_ai=used_ai)
        try:
            db.update_user_memory(
                user_id=str(user_id),
                user_name=user_name or "",
                channel_id=str(channel_id) if channel_id is not None else None,
                command_name="qa",
                summary=(question or "")[:200],
            )
        except Exception:
            pass

    except Exception:
        return


# Scheduler helpers (optional APScheduler)

def init_scheduler() -> None:
    global _PB_SCHEDULER
    if _PB_SCHEDULER is None:
        _PB_SCHEDULER = try_create_scheduler()
        if _PB_SCHEDULER:
            try:
                _PB_SCHEDULER.start()
            except Exception:
                _PB_SCHEDULER = None

def get_scheduler():
    return _PB_SCHEDULER

# ---------------- KNOWLEDGE LOADERS ----------------

def _get_nested(d: dict, path: str):
    cur = d
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur

def _format_template(template: str, context: dict) -> str:
    # Supports {club.meeting_time} style placeholders.
    def repl(m):
        key = m.group(1).strip()
        val = _get_nested(context, key)
        return str(val) if val is not None else m.group(0)
    return re.sub(r"\{([^{}]+)\}", repl, template)

def load_knowledge_json() -> dict:
    """Load club/campus memory + QA rules. Never crashes."""
    club_mem = _read_json_file(CLUB_MEMORY_JSON_PATH, {})
    campus_mem = _read_json_file(CAMPUS_MEMORY_JSON_PATH, {})
    qa_mem = _read_json_file(QA_RULES_JSON_PATH, {})
    tone_mem = _read_json_file(TONE_JSON_PATH, {})
    schedules_mem = _read_json_file(SCHEDULES_JSON_PATH, {})
    planning_mem = _read_json_file(PLANNING_NOTES_JSON_PATH, {})
    rules = qa_mem.get("rules") if isinstance(qa_mem, dict) else None
    if not isinstance(rules, list):
        rules = []
    return {
        "club": club_mem if isinstance(club_mem, dict) else {},
        "campus": campus_mem if isinstance(campus_mem, dict) else {},
        "schedules": schedules_mem if isinstance(schedules_mem, dict) else {},
        "planning_notes": planning_mem if isinstance(planning_mem, dict) else {},
        "rules": rules,
        "tone": tone_mem if isinstance(tone_mem, dict) else {},
    }

# Global knowledge cache (refreshed by !sync_knowledge)
KNOWLEDGE = load_knowledge_json()
CLUB_MEMORY = KNOWLEDGE.get("club", {})  # loaded from data/knowledge/club_memory.json


def get_hub() -> PowerBotHubService:
    global PB_HUB
    if PB_HUB is None:
        cfg = get_config()
        owner_hints = cfg.get("owner_hints")
        known_events = cfg.get("known_events")
        if isinstance(owner_hints, list):
            owner_hints = [str(x).strip() for x in owner_hints if str(x).strip()]
        else:
            owner_hints = None
        if isinstance(known_events, list):
            known_events = [str(x).strip() for x in known_events if str(x).strip()]
        else:
            known_events = None
        PB_HUB = PowerBotHubService(
            tasks_path=TASKS_PATH,
            planning_notes_path=PLANNING_NOTES_JSON_PATH,
            events_path=EVENTS_PATH,
            archive_path=EBOARD_ARCHIVE_PATH,
            club_memory_path=CLUB_MEMORY_JSON_PATH,
            eboard_log_path=EBOARD_LOG_PATH,
            owner_hints=owner_hints or None,
            known_events=known_events or None,
        )
    return PB_HUB

def rebuild_compiled_rules() -> dict:
    """Compile knowledge into a single cache file for traceability."""
    compiled = {
        "generated_at": datetime.now(timezone.utc).isoformat() + "Z",
        "club": KNOWLEDGE.get("club", {}),
        "campus": KNOWLEDGE.get("campus", {}),
        "schedules": KNOWLEDGE.get("schedules", {}),
        "planning_notes": KNOWLEDGE.get("planning_notes", {}),
        "rules": KNOWLEDGE.get("rules", []),
    }
    os.makedirs(KNOWLEDGE_DIR, exist_ok=True)
    _write_json_file(COMPILED_RULES_PATH, compiled)
    return compiled

def match_rule(question: str) -> tuple[dict | None, dict]:
    """Return (rule, trace). Substring-based matching with simple scoring."""
    q = (question or "").strip().lower()
    rules = KNOWLEDGE.get("rules", [])
    best = None
    best_score = 0
    best_trigger = None

    for rule in rules:
        if not isinstance(rule, dict):
            continue
        triggers = rule.get("match_any") or rule.get("triggers") or []
        if not isinstance(triggers, list):
            continue
        for t in triggers:
            try:
                trig = str(t).lower().strip()
            except Exception:
                continue
            if not trig:
                continue
            if trig in q:
                score = len(trig)
                if score > best_score:
                    best = rule
                    best_score = score
                    best_trigger = trig

    trace = {
        "matched": bool(best),
        "trigger": best_trigger,
        "score": best_score,
        "source_file": os.path.basename(QA_RULES_JSON_PATH),
        "source": "OFFICIAL_RULES" if best else None,
        "rule_id": best.get("id") if isinstance(best, dict) else None,
        "scope": best.get("scope") if isinstance(best, dict) else None,
    }
    return best, trace

def answer_from_rules(question: str) -> tuple[str | None, dict]:
    rule, trace = match_rule(question)
    if not rule:
        # Semantic fallback (optional)
        hits = query_index(question=question, index_dir=SEMANTIC_INDEX_DIR, k=3, min_score=0.33)
        if hits:
            top = hits[0]
            ans = top.meta.get("answer") or top.meta.get("response")
            if isinstance(ans, str) and ans.strip():
                ctx = {"club": KNOWLEDGE.get("club", {}), "campus": KNOWLEDGE.get("campus", {}), "schedules": KNOWLEDGE.get("schedules", {})}
                rendered = _format_template(ans, ctx)
                trace = {
                    **trace,
                    "matched": True,
                    "used": "SEMANTIC",
                    "confidence": "MEDIUM" if top.score < 0.5 else "HIGH",
                    "semantic_score": float(top.score),
                    "rule_id": top.meta.get("rule_id"),
                    "scope": top.meta.get("scope"),
                    "trigger": (top.meta.get("triggers") or [None])[0],
                    "source_file": "semantic/index.faiss",
                }
                return rendered, trace
        return None, trace

    ans = rule.get("answer") or rule.get("response")
    if not isinstance(ans, str) or not ans.strip():
        return None, {**trace, "matched": False, "reason": "rule_missing_answer"}

    ctx = {
        "club": KNOWLEDGE.get("club", {}),
        "campus": KNOWLEDGE.get("campus", {}),
        "schedules": KNOWLEDGE.get("schedules", {}),
        "planning_notes": KNOWLEDGE.get("planning_notes", {}),
    }
    rendered = _format_template(ans, ctx)

    # Confidence labeling (internal)
    trace["confidence"] = "HIGH" if trace["score"] >= 10 else "MEDIUM"
    trace["used"] = "OFFICIAL_RULES"
    return rendered, trace

# Build compiled_rules.json once at startup (safe if files missing)
try:
    rebuild_compiled_rules()
except Exception:
    pass
def _set_ai_enabled(enabled: bool) -> None:
    """Toggle the AI master switch and persist it."""
    global AI_ENABLED, AI_AUTO_ENABLE
    cfg = load_config()
    cfg[_AI_CONFIG_KEY] = bool(enabled)
    # If someone explicitly turns AI OFF, don't auto-reenable at next startup.
    cfg["ai_auto_enable"] = bool(enabled)
    save_config(cfg)
    AI_ENABLED = bool(enabled)
    AI_AUTO_ENABLE = bool(enabled)

EBOARD_MEMORY_PATH = os.path.join(DATA_DIR, "eboard_memory.json")
MEETING_TIME = "2:00 PM – 3:30 PM"
MEETING_ROOM = "Student Center Room 101"

# E-board role names (for permission check)
EBOARD_ROLE_NAMES = {
    "President",
    "Vice President",
    "Treasurer",
    "Events Coordinator",
    "Vice President",
    "Secretary",
    "Outreach Coordinator",
    "E-Board",
}


def is_eboard(member: discord.abc.User) -> bool:
    """True if this guild member has any E-board role."""
    try:
        roles = getattr(member, "roles", []) or []
        return any(getattr(r, "name", "") in EBOARD_ROLE_NAMES for r in roles)
    except Exception:
        return False

# Backwards-compatible alias (older code paths use this name)
def is_eboard_member(member: discord.abc.User) -> bool:
    return is_eboard(member)

# Roles that count as regular club members for auto-Q&A
MEMBER_ROLE_NAMES = {
    "Member",  # main role
    # Add more member-role names here if needed
}

# ---------------- CLUB MEMORY (STATIC KNOWLEDGE) ---------------- #


# ---------------- GEN-CHAT ARCHIVE LOADER ----------------
def load_gen_chat_archive() -> list[dict]:
    """Load gen-chat archive messages from JSON. Expected format: list of dicts."""
    try:
        if not os.path.exists(GEN_CHAT_ARCHIVE_PATH):
            return []
        with open(GEN_CHAT_ARCHIVE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Accept either {"messages":[...]} or [...]
        if isinstance(data, dict) and isinstance(data.get("messages"), list):
            return data["messages"]
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        print(f"[PowerBot] Failed to load gen-chat archive: {e}")
        return []

def search_gen_chat_archive(query: str, limit: int = 5) -> list[dict]:
    q = (query or "").strip().lower()
    if not q:
        return []
    msgs = load_gen_chat_archive()
    hits = []
    for m in msgs:
        try:
            content = str(m.get("content",""))
        except Exception:
            content = ""
        if q in content.lower():
            hits.append(m)
    # Prefer newest if timestamp present
    def ts(m):
        return m.get("timestamp") or m.get("time") or ""
    hits.sort(key=ts, reverse=True)
    return hits[:max(1, min(limit, 10))]




# ---------------- NLP GUARDS & SHORT-TERM CONTEXT ---------------- #

# Keep the bot from being "annoying": only answer when a message *looks* like a question
# or matches an explicit full trigger phrase. Also enables short follow-ups like:
#   User: "when is club?"
#   User: "where?"   (within 2 minutes)
_LAST_INTENT: dict[int, tuple[str, datetime]] = {}

def _set_last_intent(user_id: int, intent: str):
    _LAST_INTENT[user_id] = (intent, datetime.now(timezone.utc))

def _get_last_intent(user_id: int, max_age_seconds: int = 120) -> Optional[str]:
    item = _LAST_INTENT.get(user_id)
    if not item:
        return None
    intent, ts = item
    if (datetime.now(timezone.utc) - ts).total_seconds() > max_age_seconds:
        return None
    return intent

_QUESTION_STARTS = (
    "what", "when", "where", "who", "why", "how",
    "is", "are", "do", "does", "did", "can", "could", "should", "would",
    "will", "whats", "what's",
)

def looks_like_question(text: str) -> bool:
    if not text:
        return False
    t = text.strip().lower()
    if len(t) < 6:
        return False
    if "?" in t:
        return True
    # common question openers
    if t.startswith(_QUESTION_STARTS):
        return True
    # explicit "is there club today" style without question mark
    if t.startswith(("is there", "do we", "are we", "can we", "should we")):
        return True
    return False


# ---------------- ANTI-SPAM (SILENT) ----------------
# Goal: NEVER reply publicly to spam. Optionally alert E-board/mods quietly.
# This is designed to be conservative (low false positives) and fast (cheap checks first).

import time as _time
from collections import deque

_SPAM_PHONE_RE = re.compile(r"(?:\+?\d[\d\-\s\(\)]{7,}\d)")
_SPAM_URL_RE = re.compile(r"(https?://\S+|www\.\S+|wa\.me/\S+)", re.IGNORECASE)

_SPAM_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_SPAM_SNAPCHAT_RE = re.compile(r"snap(chat)?\s*[:\-]?\s*@?[A-Za-z0-9._-]{2,}", re.IGNORECASE)

# Tiered spam signals (reduces false positives)
_SPAM_OFFER_KEYWORDS = {
    # academic help / assignment-exam selling (high-risk)
    "assignments", "assignment", "due assignments", "exams", "exam", "essays", "essay",
    "research papers", "research paper", "case studies", "case study", "discussions",
    "aleks", "trigonometry", "calculus", "algebra", "stats", "statistics",
    "spss", "stata", "python", "excel", "data analysis",
    # donation/shipping-fee scam
    "donate", "donation", "shipping fee", "late husband", "downsize", "downsizing",
}
_SPAM_TONE_KEYWORDS = {
    "kindly", "hmu", "dm me", "reach out", "contact me", "contact us",
    "favorable rates", "guaranteed", "act now", "urgent", "limited time",
    "call/text", "call text", "text/call", "whatsapp",
}

# High-confidence scam patterns seen in Discord: "donation + shipping fee", "tutors + whatsapp", etc.
_SPAM_KEYWORDS = {
    # tutoring / cheating spam
    "tutor", "tutors", "coursework", "assignments", "assignment", "exams", "online classes",
    "qualified professional", "favorable rates", "guaranteed", "delivered", "booking", "hire",
    "whatsapp", "text/call", "text call", "contact us", "reach out",

    # donation / shipping-fee scam
    "donate", "donation", "shipping fee", "late husband", "downsize", "downsizing",
    "gadgets", "devices", "high demand", "legacy",

    # other common scam markers
    "limited time", "act now", "urgent", "kindly",
}

# Per-user short window tracking
_spam_msg_times: Dict[int, deque] = {}
_spam_recent_norm: Dict[int, deque] = {}
_spam_last_alert_ts: Dict[int, float] = {}
_spam_user_link_times: Dict[int, deque] = {}

def _norm_for_dupe(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    return t[:800]

def _count_urls(text: str) -> int:
    return len(_SPAM_URL_RE.findall(text or ""))

def _spam_score_and_reasons(text: str, channel_name: str = "") -> tuple[int, list[str]]:
    """
    Score-based spam detector + reasons.
    Designed to avoid false positives by requiring multiple suspicious signals.
    """
    raw = text or ""
    t = raw.lower()
    score = 0
    reasons: list[str] = []

    url_count = _count_urls(raw)

    # ---------------- Contact signals ----------------
    contact_signals = 0

    if _SPAM_PHONE_RE.search(raw):
        score += 3
        reasons.append("phone_number")
        contact_signals += 1

    if _SPAM_EMAIL_RE.search(raw):
        score += 2
        reasons.append("email_address")
        contact_signals += 1

    # Snapchat handles often appear like "Snapchat: @name"
    if "snap" in t and _SPAM_SNAPCHAT_RE.search(raw):
        score += 2
        reasons.append("snapchat_contact")
        contact_signals += 1

    if url_count >= 1:
        score += 2
        reasons.append("has_link")
        contact_signals += 1

    if ("wa.me/" in t) or ("whatsapp" in t):
        score += 3
        reasons.append("whatsapp_link")
        contact_signals += 1

    if url_count >= 2:
        score += 2
        reasons.append("many_links")

    # ---------------- Offer & tone signals ----------------
    offer_hits = 0
    tone_hits = 0

    for kw in _SPAM_OFFER_KEYWORDS:
        if kw in t:
            offer_hits += 1

    for kw in _SPAM_TONE_KEYWORDS:
        if kw in t:
            tone_hits += 1

    if offer_hits >= 2:
        score += 3
        reasons.append(f"offer_keywords:{offer_hits}")
    elif offer_hits == 1:
        score += 1
        reasons.append("offer_keyword:1")

    if tone_hits >= 1:
        score += 1
        reasons.append(f"scam_tone:{tone_hits}")

    # Legacy keyword hits (medium strength) – backward compatibility
    kw_hits = 0
    for kw in _SPAM_KEYWORDS:
        if kw in t:
            kw_hits += 1
    if kw_hits >= 2:
        score += 2
        reasons.append(f"spam_keywords:{kw_hits}")

    # Long formal letter + scam markers
    if len(t) >= 500 and ("dear students" in t or "i hope this letter finds you well" in t):
        score += 2
        reasons.append("formal_letter_pattern")

    # Channel mismatch weak signal (ads in media channels)
    if channel_name:
        ch = channel_name.lower()
        if ch in {"artwork", "photos", "media", "memes"} and (("tutor" in t) or ("donation" in t) or ("shipping fee" in t)):
            score += 1
            reasons.append("channel_mismatch")

    # Service-list formatting (✅ / lots of separators) – common in spam blasts
    if ("✅" in raw) or (raw.count("|") >= 6) or (raw.count("•") >= 6):
        score += 2
        reasons.append("service_list_format")

    # Track contact signal count for decision logic downstream
    reasons.append(f"contact_signals:{contact_signals}")

    return score, reasons


async def maybe_handle_spam(message: discord.Message) -> bool:
    """Detect likely spam/scams and handle silently (no public reply).
    Returns True if spam-handling ran (alert/action), so the caller can stop further processing.
    """
    # Only run in guilds
    if message.guild is None:
        return False

    # Skip commands (commands are handled separately)
    content = (message.content or "").strip()
    if not content or content.startswith("!"):
        return False

    # Don't flag E-board members
    if isinstance(message.author, discord.Member) and is_eboard(message.author):
        return False

    cfg = _read_json_file(CONFIG_PATH, {})
    if not bool(cfg.get("antispam_enabled", True)):
        return False

    # Exempt channels (bot/game channels, staff channels, etc.)
    try:
        ch_id = int(getattr(message.channel, "id", 0) or 0)
    except Exception:
        ch_id = 0
    exempt_ids = set()
    # Explicit list
    raw_exempt = cfg.get("antispam_exempt_channel_ids", [])
    if isinstance(raw_exempt, list):
        for v in raw_exempt:
            try:
                exempt_ids.add(int(v))
            except Exception:
                pass
    # Bot/game channels map
    bot_map = cfg.get("bot_channels", {}) if isinstance(cfg.get("bot_channels", {}), dict) else {}
    for _name, v in bot_map.items():
        try:
            exempt_ids.add(int(v))
        except Exception:
            pass
    # Common staff channels by name (if present in config)
    text_map = cfg.get("channels", {}) if isinstance(cfg.get("channels", {}), dict) else {}
    for staff_name in ("e-board", "eboard-talk", "shadow-chat", "bot-set-up"):
        try:
            if staff_name in text_map:
                exempt_ids.add(int(text_map[staff_name]))
        except Exception:
            pass

    if ch_id and ch_id in exempt_ids:
        return False

    window_seconds = int(cfg.get("antispam_window_seconds", 10))
    max_msgs_in_window = int(cfg.get("antispam_max_msgs_in_window", 7))
    dup_threshold = int(cfg.get("antispam_duplicate_threshold", 2))

    links_window_seconds = int(cfg.get("antispam_links_window_seconds", 30))
    max_links_in_window = int(cfg.get("antispam_max_links_in_window", 3))

    alert_cooldown = int(cfg.get("antispam_alert_cooldown_seconds", 120))
    action = str(cfg.get("antispam_action", "notify")).lower()
    notify_channel_name = str(cfg.get("antispam_notify_channel", "default-log"))

    now = _time.time()
    uid = int(getattr(message.author, "id", 0) or 0)

    # Update message rate window
    dq = _spam_msg_times.setdefault(uid, deque())
    dq.append(now)
    while dq and (now - dq[0]) > window_seconds:
        dq.popleft()

    # Update link window
    link_count = _count_urls(content)
    if link_count:
        lq = _spam_user_link_times.setdefault(uid, deque())
        for _ in range(link_count):
            lq.append(now)
        while lq and (now - lq[0]) > links_window_seconds:
            lq.popleft()
    else:
        lq = _spam_user_link_times.setdefault(uid, deque())
        while lq and (now - lq[0]) > links_window_seconds:
            lq.popleft()

    # Duplicate/repeat tracking
    norm = _norm_for_dupe(content)
    nq = _spam_recent_norm.setdefault(uid, deque())
    nq.append((now, norm))
    # keep last 60s
    while nq and (now - nq[0][0]) > 60:
        nq.popleft()
    dupes = sum(1 for _, txt in nq if txt == norm)

    # Content-based scoring
    score, reasons = _spam_score_and_reasons(content, getattr(message.channel, "name", "") or "")

    # Rate-based triggers (very conservative)
    if len(dq) >= max_msgs_in_window:
        score += 3
        reasons.append(f"high_rate:{len(dq)}/{window_seconds}s")

    # Link burst trigger
    if len(lq) >= max_links_in_window:
        score += 3
        reasons.append(f"link_burst:{len(lq)}/{links_window_seconds}s")

    # Duplicate trigger
    if dupes >= dup_threshold and len(norm) >= 40:
        score += 3
        reasons.append(f"duplicate:{dupes}")

    # Final decision threshold (tiered; reduces false positives)
    # Philosophy:
    # - 1 contact signal alone (email/phone/link) is NOT enough.
    # - Contact + offer language (assignments/exams/etc.) IS enough to flag.
    # - Multiple contact signals or service-list formatting strongly increases confidence.
    contact_n = 0
    offer_n = 0
    tone_n = 0
    try:
        for r in reasons:
            if r.startswith("contact_signals:"):
                contact_n = int(r.split(":", 1)[1])
            elif r.startswith("offer_keywords:"):
                offer_n = int(r.split(":", 1)[1])
            elif r == "offer_keyword:1":
                offer_n = 1
            elif r.startswith("scam_tone:"):
                tone_n = int(r.split(":", 1)[1])
    except Exception:
        pass

    has_service_list = "service_list_format" in reasons
    has_formal = "formal_letter_pattern" in reasons
    has_many_links = "many_links" in reasons

    has_offer = offer_n >= 2 or ("offer_keyword:1" in reasons and "spam_keywords" in " ".join(reasons))
    has_contact = contact_n >= 1
    multi_contact = contact_n >= 2

    # Rate-based triggers can still flag even without offer language
    rate_trigger = any(r.startswith("high_rate:") or r.startswith("link_burst:") or r.startswith("duplicate:") for r in reasons)

    # Primary flag rules:
    is_spam = False

    # 1) Offer + contact (classic assignment/exam seller)
    if has_offer and has_contact:
        is_spam = True

    # 2) Multiple contact signals + solicitation tone or service-list formatting
    if not is_spam and multi_contact and (tone_n >= 1 or has_service_list or has_many_links or has_formal):
        is_spam = True

    # 3) Very high score with rate triggers (spam floods)
    if not is_spam and rate_trigger and score >= 6 and ("has_link" in reasons or contact_n >= 1):
        is_spam = True

    # 4) Backstop: extremely high score (multiple strong indicators)
    if not is_spam and score >= 10 and has_contact:
        is_spam = True


    if not is_spam:
        return False

    # Alert cooldown
    last_alert = _spam_last_alert_ts.get(uid, 0.0)
    if (now - last_alert) < alert_cooldown:
        return True  # handled silently; don't let other modules react

    _spam_last_alert_ts[uid] = now

    # Notify staff quietly
    try:
        notify_chan = None
        notify_channel_id = cfg.get("antispam_notify_channel_id") or cfg.get("default_log_channel_id")
        if notify_channel_id is not None:
            try:
                _nid = int(notify_channel_id)
                notify_chan = message.guild.get_channel(_nid)
            except Exception:
                notify_chan = None

        if notify_chan is None:
            notify_chan = discord.utils.get(message.guild.text_channels, name=notify_channel_name)
        if notify_chan:
            snippet = content.replace("\n", " ")
            if len(snippet) > 240:
                snippet = snippet[:240] + "…"

            # Also log to SQLite (if enabled) so you can audit later.
            try:
                db = get_db()
                if db:
                    db.log_spam_event(
                        guild_id=str(getattr(message.guild, "id", "")) or None,
                        channel_id=str(getattr(message.channel, "id", "")) or None,
                        channel_name=str(getattr(message.channel, "name", "")) or None,
                        user_id=str(uid) if uid else None,
                        user_name=str(message.author),
                        score=int(score),
                        reasons=", ".join(reasons),
                        snippet=snippet,
                        jump_url=str(getattr(message, "jump_url", "")) or "",
                    )
            except Exception:
                pass

            await notify_chan.send(
                "🚨 **Possible spam/scam detected**\n"
                f"• Channel: {message.channel.mention}\n"
                f"• User: {message.author} (ID: `{uid}`)\n"
                f"• Reasons: `{', '.join(reasons)}` (score={score})\n"
                f"• Snippet: {snippet}\n"
                f"• Jump: {getattr(message, 'jump_url', 'n/a')}"
            )
    except Exception as e:
        print(f"[PowerBot] Anti-spam notify failed: {e}")

    # Optional actions (off by default)
    if "delete" in action:
        try:
            await message.delete()
        except Exception:
            pass

    if "timeout" in action and isinstance(message.author, discord.Member):
        try:
            minutes = int(cfg.get("antispam_timeout_minutes", 10))
            until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
            await message.author.timeout(until, reason="PowerBot anti-spam")
        except Exception:
            pass

    return True

# Attendance multipliers
EVENT_TYPE_MULTIPLIERS = {
    "regular": 1.0,
    "trivia": 1.1,
    "karaoke": 0.9,
    "manga": 1.0,
    "food": 1.3,
    "other": 1.0,
}

# Context modifiers
CONTEXT_MULTIPLIERS = {
    "finals": 0.7,
    "midterms": 0.85,
    "rain": 0.9,
    "highadvert": 1.1,
}

# ---------------- ACADEMIC CALENDAR ---------------- #

FALL_2025_START = date(2025, 8, 29)
FALL_2025_END = date(2025, 12, 17)
FALL_2025_FALL_BREAK_START = date(2025, 10, 18)
FALL_2025_FALL_BREAK_END = date(2025, 10, 26)
FALL_2025_THANKSGIVING_START = date(2025, 11, 26)
FALL_2025_THANKSGIVING_END = date(2025, 11, 30)
FALL_2025_FINALS_START = date(2025, 12, 1)
FALL_2025_FINALS_END = FALL_2025_END

WINTER_2026_START = date(2025, 12, 22)
WINTER_2026_END = date(2026, 1, 14)

SPRING_2026_START = date(2026, 1, 16)
SPRING_2026_END = date(2026, 5, 4)
SPRING_2026_SPRING_BREAK_START = date(2026, 3, 7)
SPRING_2026_SPRING_BREAK_END = date(2026, 3, 15)
SPRING_2026_GOOD_FRIDAY = date(2026, 4, 3)


def get_next_monday(today: date | None = None) -> date:
    """Return the date of the next Monday (or today if today is Monday)."""
    if today is None:
        today = datetime.now(timezone.utc).date()
    days_ahead = (0 - today.weekday() + 7) % 7
    return today if days_ahead == 0 else today + timedelta(days=days_ahead)


def get_academic_context(d: date) -> dict:
    """
    Given a date, return information about the academic term/phase
    and a recommended attendance multiplier.
    """
    ctx = {
        "term": "Out of known range",
        "phase": "Unknown",
        "multiplier": 1.0,
        "no_classes": False,
        "notes": [],
    }

    if FALL_2025_START <= d <= FALL_2025_END:
        ctx["term"] = "Fall 2025"

        if FALL_2025_FALL_BREAK_START <= d <= FALL_2025_FALL_BREAK_END:
            ctx["phase"] = "Fall Break"
            ctx["multiplier"] = 0.1
            ctx["no_classes"] = True
            ctx["notes"].append("Fall Break (no classes). Expect very low turnout.")
            return ctx

        if FALL_2025_THANKSGIVING_START <= d <= FALL_2025_THANKSGIVING_END:
            ctx["phase"] = "Thanksgiving Break"
            ctx["multiplier"] = 0.1
            ctx["no_classes"] = True
            ctx["notes"].append("Thanksgiving Break (no classes). Expect very low turnout.")
            return ctx

        if FALL_2025_FINALS_START <= d <= FALL_2025_FINALS_END:
            ctx["phase"] = "Finals Period"
            ctx["multiplier"] = 0.7
            ctx["notes"].append("Finals period. Students are busy, expect lower turnout.")
            return ctx

        weeks_since_start = (d - FALL_2025_START).days // 7
        if weeks_since_start <= 1:
            ctx["phase"] = "Early Semester (Week 1–2)"
            ctx["multiplier"] = 1.15
            ctx["notes"].append("High curiosity period. Events may overperform baseline.")
        elif weeks_since_start <= 5:
            ctx["phase"] = "Mid-Semester (Weeks 3–6)"
            ctx["multiplier"] = 1.0
            ctx["notes"].append("Stable attendance period.")
        else:
            ctx["phase"] = "Late Semester (before finals)"
            ctx["multiplier"] = 0.95
            ctx["notes"].append("Late semester fatigue can slightly reduce attendance.")
        return ctx

    if WINTER_2026_START <= d <= WINTER_2026_END:
        ctx["term"] = "Winter 2026"
        ctx["phase"] = "Winter Session"
        ctx["multiplier"] = 0.4
        ctx["notes"].append("Winter session. Many students are away; turnout may be low.")
        return ctx

    if SPRING_2026_START <= d <= SPRING_2026_END:
        ctx["term"] = "Spring 2026"

        if SPRING_2026_SPRING_BREAK_START <= d <= SPRING_2026_SPRING_BREAK_END:
            ctx["phase"] = "Spring Break"
            ctx["multiplier"] = 0.1
            ctx["no_classes"] = True
            ctx["notes"].append("Spring Break (no classes). Expect very low turnout.")
            return ctx

        if d == SPRING_2026_GOOD_FRIDAY:
            ctx["phase"] = "Good Friday (no classes)"
            ctx["multiplier"] = 0.2
            ctx["no_classes"] = True
            ctx["notes"].append("Good Friday (no classes). Turnout likely minimal.")
            return ctx

        weeks_since_start = (d - SPRING_2026_START).days // 7
        if weeks_since_start <= 1:
            ctx["phase"] = "Early Semester (Week 1–2)"
            ctx["multiplier"] = 1.15
            ctx["notes"].append("High curiosity period. Events may overperform baseline.")
        elif weeks_since_start <= 5:
            ctx["phase"] = "Mid-Semester (Weeks 3–6)"
            ctx["multiplier"] = 1.0
            ctx["notes"].append("Stable attendance period.")
        else:
            ctx["phase"] = "Late Semester (before finals)"
            ctx["multiplier"] = 0.95
            ctx["notes"].append("Late semester fatigue can slightly reduce attendance.")
        return ctx

    ctx["notes"].append("Date is outside the Fall 2025 / Spring 2026 range.")
    return ctx

# ---------------- DISCORD SETUP ---------------- #

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# Inject PowerBot handles for cogs and helpers
bot._pb_get_knowledge = lambda: KNOWLEDGE
bot._pb_get_config = lambda: config
bot._pb_save_config = save_config
bot._pb_get_db = get_db
bot._pb_owner_id = OWNER_ID
bot._pb_knowledge_dir = KNOWLEDGE_DIR
bot._pb_semantic_dir = SEMANTIC_INDEX_DIR
PB_EXTENSIONS = ["cogs.ops", "cogs.schedules", "cogs.notes"]
_PB_EXTENSIONS_LOADED = False


# ---------------- GLOBAL: ALL COMMANDS ARE E-BOARD ONLY ----------------
@bot.check
async def _eboard_only_all_commands(ctx: commands.Context) -> bool:
    # Only gate real commands
    if not ctx.command:
        return True
    author = getattr(ctx, 'author', None)
    if _is_owner(author):
        return True
    return is_eboard(author)





# ---------------- EXTENSION LOADER ---------------- #

@bot.event
async def on_ready():
    global _PB_EXTENSIONS_LOADED
    if _PB_EXTENSIONS_LOADED:
        return
    try:
        for ext in PB_EXTENSIONS:
            try:
                await bot.load_extension(ext)
                print(f"[PowerBot] Loaded extension: {ext}")
            except Exception as e:
                print(f"[PowerBot] Failed to load extension {ext}: {e}")
        _PB_EXTENSIONS_LOADED = True
    except Exception as e:
        print(f"[PowerBot] Extension loader error: {e}")


# ---------------- AI ADVISOR ENGINE ----------------
# Optional AI-powered replies. Safe-by-default:
# - Only answers when someone addresses PowerBot OR within a short follow-up window.
# - Won’t answer E-board-only planning/ops questions for regular members.
# - Fails closed (if AI is unavailable, bot keeps running without AI).

import time
FOLLOWUP_WINDOW_SECONDS = 40  # follow-ups after someone addresses PowerBot

# user_id -> (expires_ts, channel_id)
_ai_followups: Dict[int, Tuple[float, int]] = {}

# E-board assistant anti-spam cooldown
EBOARD_ASSIST_COOLDOWN_SECONDS = 180  # 3 minutes
_eboard_last_assist_ts: Dict[int, float] = {}  # channel_id -> last reply timestamp

# user_id -> number of times we've responded to simple greetings during the follow-up window
_ai_greet_counts: Dict[int, int] = {}


def _now_ts() -> float:
    return time.time()

def _is_followup(message: discord.Message) -> bool:
    rec = _ai_followups.get(message.author.id)
    if not rec:
        return False
    exp_ts, ch_id = rec
    if message.channel.id != ch_id:
        return False
    if _now_ts() > exp_ts:
        _ai_followups.pop(message.author.id, None)
        _ai_greet_counts.pop(message.author.id, None)
        return False
    return True

def _mark_followup(message: discord.Message):
    _ai_followups[message.author.id] = (_now_ts() + FOLLOWUP_WINDOW_SECONDS, message.channel.id)

def _directed_at_powerbot(bot: commands.Bot, message: discord.Message) -> bool:
    txt = (message.content or "").strip()
    low = txt.lower()

    # Mentions
    if bot.user and bot.user.mentioned_in(message):
        return True

    # Starts with the name (common pattern)
    if low.startswith("powerbot"):
        return True

    # Simple greetings
    if low in {"powerbot", "hey powerbot", "hi powerbot"}:
        return True

    return False

def _looks_like_real_request(message: discord.Message) -> bool:
    """Avoid accidental AI replies. Require a question mark or request-y phrasing.
    Special-case messages that start with 'powerbot ...' so they count as requests.
    """
    txt = (message.content or "").strip().lower()
    if len(txt) < 2:
        return False

    # If they start with "powerbot ...", evaluate the rest too
    if txt.startswith("powerbot"):
        rest = txt[len("powerbot"):].strip(" ,:-")
        if not rest:
            return False

        # Treat most "powerbot <anything>" as a real request so it doesn't ignore people.
        # But avoid firing AI for pure greetings / pings.
        greeting_only = {
            "hi", "hey", "hello", "yo", "sup", "hiya",
            "good morning", "good afternoon", "good evening",
            "thanks", "thank you",
        }
        if rest in greeting_only:
            return False

        # If there's a question mark, definitely a request
        if "?" in rest:
            return True

        # Common request-y starters / verbs
        starters = (
            "what ", "why ", "how ", "when ", "where ", "who ",
            "can you", "could you", "tell me", "explain", "help", "recommend", "suggest",
            "give me", "make me", "write", "translate", "summarize",
            "do you", "are you", "is it", "what do",
            "schedule", "meeting", "club", "info", "rules", "commands",
        )
        if rest.startswith(starters):
            return True

        # Otherwise, if they addressed PowerBot and wrote actual content, count it as a request.
        return True



    if "?" in txt:
        return True

    starters = (
        "what ", "why ", "how ", "when ", "where ", "who ",
        "can you", "could you", "tell me", "explain", "help", "recommend", "suggest",
        "give me", "make me", "write", "translate", "summarize",
        "do you", "are you", "is it", "what do",
    )
    return txt.startswith(starters)

def _is_club_related(text: str) -> bool:
    """Heuristic: detect club/ops questions that should be answered by rule-based logic first."""
    t = (text or "").lower()

    # If it's a command, it's not a free-form question.
    if t.strip().startswith("!"):
        return True

    keywords = (
        # club basics
        "club", "club meeting", "meeting time", "meeting room", "where is", "what room",
        "schedule", "when is club", "club today", "is there club", "meeting today",
        "meeting room", "where is", "what room", "announcements", "roles", "introductions",
        "eboard", "e-board", "e board",

        # powerbot help/about
        "powerbot help", "what can you do", "commands", "!help", "how do i use",

        # events / turnout
        "event", "events", "karaoke", "trivia", "jeopardy", "manga", "drawing",
        "attendance", "turnout", "forecast", "simulate", "rsvp",

        # planning / money / logistics
        "budget", "reimburse", "reimbursement", "receipt", "invoice",
        "food", "kfc", "pizza", "snacks", "drinks", "utensils", "plates", "cups", "napkins",
        "promo", "instagram", "insta", "flyer", "email",
    )
    return any(k in t for k in keywords)



def _is_ops_planning_question(text: str) -> bool:
    """Topics we want to keep E-board only (planning, budgeting, reimbursement, ops)."""
    t = (text or "").lower()
    keywords = [
        "budget", "reimbursement", "funding", "purchase", "receipt", "waiver",
        "room reservation", "reserve a room", "forms", "vendor", "policy", "risk",
        "event planning", "planning", "agenda", "minutes", "eboard", "e-board",
        "exec board", "officer", "ops", "logistics",
    ]
    return any(k in t for k in keywords)

def _power_style_prefix() -> str:
    # Power-ish, cute, and human — without slang or rudeness
    return random.choice([
        "Okay!! ",
        "Hehe— ",
        "PowerBot reporting! ⚡ ",
        "Mhm! ",
        "I got you. ",
        "Alright— ",
        "Yes yes! ",
    ])

# AI backend probe (optional)
AI_AVAILABLE = False
AI_BACKEND_INFO = ""
AI_LAST_ERROR: str = ""
AI_LAST_ERROR_DETAIL: str = ""

def _probe_ollama(host: str) -> tuple[bool, str]:
    """Best-effort Ollama liveness probe. Never raises."""
    try:
        import urllib.request
        import json as _json
        req = urllib.request.Request(f"{host}/api/version", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=1.8) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        try:
            data = _json.loads(raw) if raw else {}
        except Exception:
            data = {}
        ver = ""
        if isinstance(data, dict):
            ver = str(data.get("version") or "").strip()
        return True, ver
    except Exception:
        return False, ""

if AI_BACKEND in ("none", "off", "disabled"):
    AI_AVAILABLE = False
    AI_BACKEND_INFO = "disabled"
elif AI_BACKEND == "ollama":
    ok, ver = _probe_ollama(OLLAMA_HOST)
    AI_AVAILABLE = bool(ok)
    AI_BACKEND_INFO = f"ollama{(' ' + ver) if ver else ''}".strip()
else:
    AI_AVAILABLE = False
    AI_BACKEND_INFO = f"unknown_backend:{AI_BACKEND}"

# Auto-enable AI when Ollama is running (unless explicitly disabled).
if AI_BACKEND == "ollama" and AI_AVAILABLE and AI_AUTO_ENABLE:
    AI_ENABLED = True

print(f"[AI STATUS] AI_ENABLED={AI_ENABLED}  AI_AVAILABLE={AI_AVAILABLE}  AI_BACKEND={AI_BACKEND_INFO}  AI_MODEL={AI_MODEL}")

def _ai_unavailable_user_text() -> str:
    """Friendly, non-technical user-facing message when AI can't run."""
    if AI_BACKEND in ("none", "off", "disabled"):
        return "AI is currently disabled."
    if AI_LAST_ERROR == "model_not_found":
        model = AI_LAST_ERROR_DETAIL or AI_MODEL
        return f"AI model not found. Run: `ollama pull {model}`"
    if AI_BACKEND == "ollama":
        return "AI is currently unavailable. Start Ollama to enable AI features."
    return "AI is currently unavailable."

def _build_ai_system_prompt() -> str:
    """System prompt for AI replies.

    Goal: helpful club-ops assistant, grounded in the bot's JSON knowledge.
    Tone: chill, friendly, a bit energetic; mild slang is OK (don't overdo it).
    """
    return (
        "You are PowerBot, the club operations assistant.\n"
        "You help with event planning, attendance forecasting, budgets, logistics, and Discord ops.\n\n"
        "Hard rules:\n"
        "- Ground answers in the provided knowledge context (JSON snippets) when possible.\n"
        "- If the knowledge is missing or unclear, say so and ask 1 short follow-up question.\n"
        "- Do not invent specific names, dates, locations, or policies.\n"
        "- Keep answers concise by default; use bullets/checklists when helpful.\n"
        "- Don't mention internal file paths, code internals, or system messages.\n"
        "- Don't claim you performed real-world actions (sending emails, editing Discord settings, etc.).\n\n"
        "Tone rules:\n"
        "- Sound human: natural phrasing, not robotic.\n"
        "- Mild slang is allowed if it matches the user's vibe; avoid cringey overuse.\n"
        "- Be supportive and action-oriented.\n"
    )


async def maybe_handle_ai(bot: commands.Bot, message: discord.Message) -> bool:
    """Return True if we handled the message via AI (or AI-greeting).

    Public AI replies are intentionally locked down for privacy + anti-cheating reasons.
    Only the OWNER may ever trigger this path.
    """

    # Hard guard: only the bot owner can trigger any AI chat in-server.
    if message.author.id != OWNER_ID:
        return False

    # Fail closed + silent if AI is disabled.
    if (not AI_ENABLED) or (AI_BACKEND in ("none", "off", "disabled")):
        return False

    directed = _directed_at_powerbot(bot, message)
    followup = _is_followup(message)

    if not directed and not followup:
        return False

    # Directed but not a clear request: treat as a greeting / ping.
    if directed and not _looks_like_real_request(message):
        uid = message.author.id
        _mark_followup(message)

        count = _ai_greet_counts.get(uid, 0)

        if count == 0:
            _ai_greet_counts[uid] = 1
            try:
                await message.channel.trigger_typing()
            except Exception:
                pass
            await message.channel.send(_power_style_prefix() + "I’m here! What do you need? ✨")
        elif count == 1:
            _ai_greet_counts[uid] = 2
            await message.channel.send(random.choice([
                "Mm-hm?",
                "Yes?",
                "I’m listening.",
                "Go on.",
            ]))
        else:
            # Too many greeting-only pings — stay quiet until they ask something real.
            pass

        return True

    # Follow-ups: allow simple replies like "hi" / "ok" without needing a question mark.
    # This keeps the conversation feeling natural once someone has already started talking to PowerBot.
    if followup and (not directed) and (not _looks_like_real_request(message)):
        pass
    else:
        # If not a request, ignore (prevents random replies)
        if not _looks_like_real_request(message):
            return False

    # E-board-only planning guardrail (members can't use AI for ops)
    is_member_eboard = isinstance(message.author, discord.Member) and is_eboard(message.author)
    if (not is_member_eboard) and _is_ops_planning_question(message.content or ""):
        _mark_followup(message)
        await message.channel.send(
            _power_style_prefix()
            + "That’s an E-board planning thing. Ask an E-board member in the planning channels."
        )
        return True

    _mark_followup(message)

    user_text = (message.content or "").strip()
    if user_text.lower().startswith("powerbot"):
        user_text = user_text[len("powerbot"):].lstrip(" ,:-")
    _ai_greet_counts.pop(message.author.id, None)

    system_prompt = _build_ai_system_prompt()
    context = _club_context_snippet()

    import asyncio

    try:
        async with message.channel.typing():





































            reply = await asyncio.wait_for(asyncio.to_thread(_call), timeout=20)

        reply = (reply or "").strip()
        if not reply:
            await message.channel.send(_power_style_prefix() + "I blanked out 😵‍💫 Try again.")
            return True

        # a tiny bit of Power flair sometimes
        if not any(e in reply for e in ["🔥", "✨", "🎌", "😤"]):
            if random.random() < 0.35:
                reply += " ✨"

        await message.channel.send(_power_style_prefix() + reply)
        return True

    except asyncio.TimeoutError:
        await message.channel.send(_power_style_prefix() + "Wait— I blanked for a second 😅 Try again?")
        return True
    except Exception as e:
        print("[AI ERROR]", repr(e))
        await message.channel.send(_power_style_prefix() + "Oops… something snapped behind the scenes. Try again in a moment.")
        return True
async def handle_member_autoresponse(message: discord.Message) -> bool:
    """Rule-based auto answers for members.

    IMPORTANT: This ONLY triggers when PowerBot is explicitly called (mention or name) AND the message looks like a full question.
    This prevents random interruptions in casual chat.
    """
    if not message.guild:
        return False

    # Silence mode: only respond to public mentions if explicitly enabled.
    if not config.get("public_autoresponse_enabled", False):
        return False

    content = (message.content or "").strip()
    if not content:
        return False

    # Must explicitly call the bot
    talked_to_bot = False
    try:
        if bot.user and bot.user.mentioned_in(message):
            talked_to_bot = True
    except Exception:
        talked_to_bot = False

    if not talked_to_bot:
        if re.search(r"\bpower\s*bot\b", content, flags=re.IGNORECASE):
            talked_to_bot = True

    if not talked_to_bot:
        return False

    # Strip mentions + name for question detection
    cleaned = re.sub(r"<@!?\d+>", "", content).strip()
    cleaned = re.sub(r"\bpower\s*bot\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip(" ,.;:!?-–—\"'")

    # Must be a complete question
    if not looks_like_question(cleaned):
        return False

    async with message.channel.typing():
        # 1) direct rule match
        rule_ans = answer_from_rules(cleaned)
        if rule_ans:
            await message.reply(rule_ans, mention_author=False)
            record_followup(message.channel.id, message.author.id, message.id)
            return True

        # 2) semantic Q&A match (if available)
        try:
            hits = query_index(cleaned, k=1, min_score=0.45)
        except Exception:
            hits = []
        if hits:
            top = hits[0]
            ans = (top.get("answer") or top.get("text") or "").strip()
            if ans:
                await message.reply(ans, mention_author=False)
                record_followup(message.channel.id, message.author.id, message.id)
                return True

        # 3) last-resort: helpful nudge
        await message.reply(
            "I don’t have a solid answer for that from my saved club knowledge yet. "
            "Try asking with a bit more detail (who/what date/which event), and I’ll help. 🙂",
            mention_author=False,
        )
        record_followup(message.channel.id, message.author.id, message.id)
        return True

async def maybe_handle_owner_dm_ai(message: discord.Message) -> bool:
    """Owner-only DM AI for the configured bot owner."""
    if message.guild is not None:
        return False
    if message.author.id != OWNER_ID:
        return False

    content = (message.content or "").strip()
    if not content:
        return True  # ignore empty DMs

    # Keep the prompt compact; rely on semantic retrieval + upcoming events.
    ctx = build_private_consult_context("Direct Messages")
    prompt = (
        f"{ctx}\n\n"
        f"User (bot owner) DM message: {content}\n\n"
        "Reply as PowerBot. Be chill, friendly, and helpful.\n"
        "Use the provided context and relevant knowledge; if missing, say what you need."
    )

    try:
        async with message.channel.typing():
            reply = await ai_generate_text(prompt, max_tokens=900, force=True)
    except Exception as e:
        logger.exception("DM AI failed")
        reply = None

    if not reply:
        # Don’t spam errors; keep it short.
        await message.reply("⚠️ I couldn’t reach my AI brain right now. Try again in a minute.")
        return True

    await message.reply(reply)
    return True



# ---------------- ACTIVITY TRACKING (SILENT) ---------------- #

def _count_links(text: str) -> int:
    try:
        if not text:
            return 0
        t = text.lower()
        return t.count("http://") + t.count("https://")
    except Exception:
        return 0


async def maybe_log_activity(message: discord.Message) -> None:
    """Silently log daily activity aggregates (no message content stored)."""
    try:
        cfg = get_config()
        if not cfg.get("activity_tracking_enabled", True):
            return
        db = get_db()
        if not db:
            return
        day = datetime.now(timezone.utc).date().isoformat()
        chars = len(message.content or "")
        links = _count_links(message.content or "")
        attachments = len(getattr(message, "attachments", []) or [])
        # Resolve IDs as strings for DB
        gid = str(message.guild.id) if message.guild else None
        cid = str(message.channel.id) if message.channel else None
        uid = str(message.author.id) if message.author else None
        uname = str(message.author) if message.author else None
        db.incr_activity_daily(
            day=day,
            guild_id=gid,
            channel_id=cid,
            user_id=uid,
            user_name=uname,
            chars=chars,
            links=links,
            attachments=attachments,
        )
    except Exception:
        return

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Always let explicit commands run first
    content = (message.content or "").strip()
    if content.startswith("!"):
        await bot.process_commands(message)
        return

    # Owner DM AI (no consult required)
    if await maybe_handle_owner_dm_ai(message):
        return

    # Activity tracking (silent; no content stored)
    try:
        await maybe_log_activity(message)
    except Exception:
        pass

    # Silent anti-spam detection (never replies in public). If it triggers, stop processing.
    try:
        if await maybe_handle_spam(message):
            return
    except Exception as e:
        print(f"[PowerBot] Anti-spam error: {e}")

    # Owner-only Private Consult Mode (AI conversation)
    if await maybe_handle_private_consult(message):
        return

    # Public channels: no auto replies.
    # PowerBot only speaks via commands or explicit owner/private AI flows.
    return

# ----------------- PLANNING TOOLS --------------- #



async def supplies_cmd(ctx: commands.Context, per_person: float):
    base = config.get("base_attendance", CLUB_MEMORY.get("baseline_attendance_default", 15))
    needed = base * per_person
    with_buffer = needed * 1.2

    await ctx.send(
        "Supply estimate:\n"
        f"- Baseline attendance: {base}\n"
        f"- Per person: {per_person}\n"
        f"- Needed: {needed:.1f}\n"
        f"- With 20% buffer: {with_buffer:.1f}"
    )


def build_checklist_steps(event_type: str) -> list[str]:
    common = [
        "Confirm date, time, and room.",
        "Check campus student activities requirements/forms.",
        "Create announcement and at least one reminder.",
        "Prepare slides or agenda.",
        "Assign roles to E-board members.",
        "Set up attendance tracking (sheet/QR).",
    ]

    specific = {
        "regular": ["Plan 1–2 low-pressure activities."],
        "trivia": [
            "Finalize trivia questions and answers.",
            "Prepare prizes.",
            "Test projector / laptop.",
        ],
        "karaoke": [
            "Test microphone and speakers.",
            "Decide how to manage the song queue.",
        ],
        "manga": [
            "Print blank manga sheets.",
            "Bring pencils, pens, and erasers.",
        ],
        "food": [
            "Confirm food order and delivery time.",
            "Confirm any campus policy/waiver requirements.",
        ],
    }

    return common + specific.get(event_type.lower(), [])



def _command_catalog() -> dict[str, list[tuple[str, str]]]:
    return {
        "Main": [
            ("!pb <request>", "command hub (primary interface)"),
            ("!help", "show the current command map"),
            ("!examples", "quick examples for the best commands"),
            ("!qa <question>", "manual grounded club/campus Q&A"),
            ("!advisor <question>", "grounded ops advice with optional AI"),
            ("!club [mode]", "club dashboard / analytics snapshot"),
            ("!budget [amount]", "show or set budget total"),
            ("!expense <amount> <category> [note]", "log an expense"),
        ],
        "Planning": [
            ("!events", "event hub"),
            ("!events plan <type> [date] [context]", "full plan + forecast + checklist"),
            ("!events simulate <type> [date] [context]", "scenario compare"),
            ("!events promo <type> [date]", "promo timeline"),
            ("!events review <id|name>", "post-event review"),
            ("!events roi <id|name>", "cost efficiency review"),
            ("!plan suggest", "best next event type"),
            ("!plan compare <type1> <type2>", "compare event types"),
            ("!agenda <type>", "run-of-show + checklist"),
        ],
        "Knowledge": [
            ("!notes [keywords]", "search planning notes"),
            ("!note <id>", "open a planning note"),
            ("!cosplay", "shortcut to cosplay planning note"),
            ("!schedule <name> [day]", "show a saved schedule"),
            ("!free <name> <day>", "show free windows"),
        ],
    }


@bot.command(name="help")
async def help_cmd(ctx: commands.Context):
    embed = discord.Embed(
        title="🤖 PowerBot Commands",
        description="Cleaned-up command map. Legacy one-off commands are still supported, but the hub commands below are the main path.",
        color=0x2A9D8F,
    )
    for section, rows in _command_catalog().items():
        embed.add_field(name=section, value="\n".join(f"`{cmd}` — {desc}" for cmd, desc in rows)[:1024], inline=False)
    footer = "command-only in public channels"
    if POWERBOT_VERSION:
        footer = f"Version {POWERBOT_VERSION} • " + footer
    embed.set_footer(text=footer)
    await ctx.send(embed=embed)


@bot.command(name="examples")
async def examples_cmd(ctx: commands.Context):
    lines = [
        "📘 **PowerBot Examples**",
        "- `!pb my tasks`",
        "- `!pb add task for President to confirm room by Friday high priority for welcome-week`",
        "- `!pb due this week`",
        "- `!pb summarize the last eboard discussion`",
        "- `!pb what still needs to be done for welcome-week`",
        "- `!pb status of welcome-week`",
        "- `!pb upcoming`",
        "- `!qa when is club`",
        "- `!advisor should we do food or trivia next Monday?`",
        "- `!events plan food 2026-04-06 collab strong promo`",
        "- `!budget`",
        "- `!expense 84.50 food event=12 snacks + drinks`",
        "- `!notes event_info`",
    ]
    await ctx.send("\n".join(lines))


@bot.group(name="ai", invoke_without_command=True)
async def ai_group(ctx: commands.Context):
    if not _is_owner(getattr(ctx, "author", None)):
        await ctx.send(_owner_denied_text())
        return
    await ctx.send(f"AI status: enabled={AI_ENABLED} • available={AI_AVAILABLE} • backend={AI_BACKEND_INFO} • model={AI_MODEL}")


@ai_group.command(name="status")
async def ai_status_cmd(ctx: commands.Context):
    if not _is_owner(getattr(ctx, "author", None)):
        await ctx.send(_owner_denied_text())
        return
    await ctx.send(f"AI status: enabled={AI_ENABLED} • available={AI_AVAILABLE} • backend={AI_BACKEND_INFO} • model={AI_MODEL}")


@ai_group.command(name="on")
async def ai_on_cmd(ctx: commands.Context):
    if not _is_owner(getattr(ctx, "author", None)):
        await ctx.send(_owner_denied_text())
        return
    _set_ai_enabled(True)
    await ctx.send("✅ AI is now ON.")


@ai_group.command(name="off")
async def ai_off_cmd(ctx: commands.Context):
    if not _is_owner(getattr(ctx, "author", None)):
        await ctx.send(_owner_denied_text())
        return
    _set_ai_enabled(False)
    await ctx.send("🛑 AI is now OFF.")


@bot.command(name="pb")
async def powerbot_hub_cmd(ctx: commands.Context, *, request: str = ""):
    """PowerBot natural-language command hub."""
    hub = get_hub()
    if not request.strip():
        await _send_discord_long(ctx.channel, hub.help_text())
        return

    try:
        display_name = getattr(ctx.author, "display_name", None) or getattr(ctx.author, "name", "Member")
        result = hub.handle(request, user_name=display_name)
        await _send_discord_long(ctx.channel, result.text)
    except Exception as e:
        logger.exception("powerbot_hub_failed", exc_info=e)
        await ctx.send("⚠️ The command hub hit an error. Please try again in a moment.")


@bot.command(name="qa")
async def qa_cmd(ctx: commands.Context, *, question: str = ""):
    if not question.strip():
        await ctx.send("Usage: `!qa <question>`")
        return

    answer, trace = answer_from_rules(question)
    used_ai = False
    source_bits: list[str] = []

    if answer:
        source_bits.append(trace.get("used") or trace.get("source") or "rules")
    else:
        snippets: list[str] = []
        for archive_path in [GEN_CHAT_ARCHIVE_PATH, os.path.join(KNOWLEDGE_DIR, "club_info_snippets_archive.json"), EBOARD_ARCHIVE_PATH]:
            snippets.extend(_search_snippet_archive(archive_path, question, limit=2))
        if snippets:
            answer = "Here’s the closest grounded info I found:\n" + "\n".join(snippets[:3])
            source_bits.append("archives")

    if not answer and AI_ENABLED and _is_owner(getattr(ctx, "author", None)):
        ctx_blob = _build_consult_context(question)
        answer = await ai_generate_text(question, context=ctx_blob, max_tokens=320)
        if answer:
            used_ai = True
            source_bits.append("AI")

    if not answer:
        answer = "I don’t have a reliable grounded answer for that in the current knowledge yet."

    confidence = trace.get("confidence") or ("MEDIUM" if source_bits else "LOW")
    suffix = f"\n\n*Source:* {', ' .join(source_bits) if source_bits else 'fallback'} • *Confidence:* {confidence}"
    await _send_discord_long(ctx.channel, answer + suffix)
    try:
        log_qa_interaction(
            guild_id=str(ctx.guild.id) if ctx.guild else None,
            channel_id=str(ctx.channel.id) if ctx.channel else None,
            user_id=str(ctx.author.id),
            user_name=str(ctx.author),
            question=question,
            answer=answer,
            trace=trace or {},
            used_ai=used_ai,
        )
    except Exception:
        pass


@bot.command(name="advisor")
async def advisor_cmd(ctx: commands.Context, *, question: str = ""):
    if not question.strip():
        await ctx.send("Usage: `!advisor <question>`")
        return

    metrics_lines: list[str] = []
    try:
        events = load_events()
        valid = [e for e in events if isinstance(e, dict) and isinstance(e.get("attendance"), (int, float))]
        if valid:
            avg_att = sum(float(e.get("attendance") or 0) for e in valid) / len(valid)
            metrics_lines.append(f"Average logged attendance: {avg_att:.1f}")
            last = valid[-1]
            metrics_lines.append(f"Last event: {last.get('event_type', 'event')} with attendance {last.get('attendance', '?')}")
    except Exception:
        pass
    try:
        cfg = get_config()
        metrics_lines.append(f"Budget total: ${float(cfg.get('budget_total') or 0):,.2f}")
        metrics_lines.append(f"Base attendance model: {float(cfg.get('base_attendance') or 0):.1f}")
    except Exception:
        pass

    grounded: list[str] = []
    for archive_path in [os.path.join(KNOWLEDGE_DIR, "club_info_snippets_archive.json"), EBOARD_ARCHIVE_PATH]:
        grounded.extend(_search_snippet_archive(archive_path, question, limit=2))

    ctx_blob = _build_consult_context(question)
    if metrics_lines:
        ctx_blob = "Club metrics:\n" + "\n".join(metrics_lines) + "\n\n" + ctx_blob
    if grounded:
        ctx_blob += "\n\nRelevant archive snippets:\n" + "\n".join(grounded[:4])

    reply = None
    if AI_ENABLED:
        reply = await ai_generate_text(
            question,
            system=(
                "You are PowerBot, a student org operations advisor. "
                "Be practical, concise, and grounded in the provided context. "
                "If the context is thin, say what is uncertain instead of inventing details."
            ),
            context=ctx_blob,
            max_tokens=420,
        )

    if not reply:
        forecast_hint = None
        for et in ["food", "trivia", "karaoke", "manga", "regular"]:
            if et in question.lower():
                forecast_hint = smart_forecast_3(et, None, question)
                break
        lines = ["Here’s my grounded take:"]
        if grounded:
            lines.append("- Archive context suggests this has been discussed before.")
        if forecast_hint:
            lines.append(f"- Forecast for `{forecast_hint['event_type']}` is around **{forecast_hint['expected']:.0f}** attendees.")
        lines.append("- Keep the plan simple, promote early, and tie the event choice to budget + current semester timing.")
        if metrics_lines:
            lines.append("- Current metrics considered: " + "; ".join(metrics_lines[:3]))
        reply = "\n".join(lines)

    await _send_discord_long(ctx.channel, reply)

@bot.command(name="agenda", aliases=["runofshow", "ros"])
async def agenda_cmd(ctx: commands.Context, event_type: str = "regular"):
    """Generate a simple run-of-show + checklist for an event type."""
    et = (event_type or "regular").lower().strip()

    templates = {
        "gbm": [("Intro / welcome", 5), ("What we do + upcoming events", 8), ("Quick icebreaker", 10), ("Main activity", 25), ("Announcements + how to join", 7), ("Wrap / socials", 5)],
        "regular": [("Welcome + quick updates", 5), ("Main activity", 30), ("Announcements + reminders", 5), ("Hangout / questions", 10)],
        "trivia": [("Welcome + rules", 5), ("Round 1", 10), ("Round 2", 10), ("Final round", 10), ("Score + prizes", 5), ("Wrap", 3)],
        "karaoke": [("Welcome + rules", 5), ("Set up / test audio", 5), ("Karaoke block 1", 20), ("Break / rotations", 5), ("Karaoke block 2", 20), ("Wrap", 5)],
        "food": [("Welcome + quick update", 5), ("Food distribution", 15), ("Social + photos", 25), ("Wrap + cleanup", 10)],
        "fair": [("Arrive + setup table", 20), ("Active tabling / signups", 90), ("Wrap + cleanup", 15)],
        "game": [("Welcome + rules", 5), ("Warmup round", 10), ("Main game block", 25), ("Finale / tiebreaker", 10), ("Wrap", 5)],
    }

    if et in {"introduction", "intro", "generalbody", "general body", "gbm"}:
        key = "gbm"
    elif et in {"tabling", "clubfair", "club fair", "fair"}:
        key = "fair"
    elif et in {"game", "game night", "boardgame", "board game"}:
        key = "game"
    else:
        key = et if et in templates else "regular"

    blocks = templates[key]
    total = sum(m for _, m in blocks)

    lines = [f"🗓️ **Run-of-show ({key})** — ~{total} min", ""]
    for name, mins in blocks:
        lines.append(f"- {mins} min — {name}")

    lines.append("")
    lines.append("✅ **Checklist**")
    for i, step in enumerate(build_checklist_steps(key), start=1):
        lines.append(f"{i}. {step}")

    msg = "\n".join(lines)
    if len(msg) > 1900:
        msg = msg[:1900] + "\n\n...(truncated)"
    await ctx.send(msg)


async def checklist_event_cmd(ctx: commands.Context, event_type: str = "regular"):
    steps = build_checklist_steps(event_type)
    lines = [f"Checklist for {event_type} event:"]
    for i, step in enumerate(steps, start=1):
        lines.append(f"{i}. {step}")

    await ctx.send("\n".join(lines))


@bot.command(name="next_monday")
async def next_monday_cmd(ctx: commands.Context):
    next_mon = get_next_monday()
    info = get_academic_context(next_mon)
    lines = [
        f"📅 Next Monday meeting date: **{next_mon.isoformat()}**",
        f"- Term: **{info['term']}**",
        f"- Phase: **{info['phase']}**",
        f"- Recommended attendance multiplier: **{info['multiplier']:.2f}x**",
    ]

    vibe = "Normal meeting (regular or trivia) is fine."
    if "Finals" in info["phase"]:
        vibe = "Chill, low-pressure, maybe light food or a study-break vibe."
    elif "Break" in info["phase"]:
        vibe = "Campus will be quiet; consider skipping or doing a very small social if anyone is around."
    elif "Early Semester" in info["phase"]:
        vibe = "High curiosity period – great time for a flashy event (trivia, intro social, or light food)."
    elif "Late Semester" in info["phase"]:
        vibe = "People are getting tired; choose cozy, low-stress events."

    lines.append(f"- Suggested vibe: **{vibe}**")

    if info["notes"]:
        lines.append("")
        lines.append("Notes:")
        for n in info["notes"]:
            lines.append(f"- {n}")

    await ctx.send("\n".join(lines))




@bot.command(name="suggest_next_event")
async def suggest_next_event_cmd(ctx: commands.Context):
    """Suggest the best event type for the next Monday meeting (based on your multipliers)."""
    # E-board only (or owner anywhere)
    if not (is_eboard(getattr(ctx, "author", None)) or _is_owner(getattr(ctx, "author", None))):
        await ctx.send("⛔ This command is limited to **E-board**.")
        return

    cfg = get_config()
    base = float(cfg.get("base_attendance") or 17)
    next_mon = get_next_monday()
    info = get_academic_context(next_mon)
    ctx_mult = float(info.get("multiplier", 1.0) or 1.0)

    event_mults = ((cfg.get("multipliers") or {}).get("event_type") or {})
    if not isinstance(event_mults, dict) or not event_mults:
        await ctx.send("No event_type multipliers found in config.")
        return

    scored = []
    for k, v in event_mults.items():
        try:
            m = float(v or 1.0)
            pred = base * ctx_mult * m
            scored.append((k, pred, m))
        except Exception:
            continue
    scored.sort(key=lambda x: x[1], reverse=True)

    lines = [
        f"📅 Next Monday: **{next_mon.isoformat()}**",
        f"Phase: **{info.get('phase')}** (context multiplier **{ctx_mult:.2f}x**)",
        "",
        "Top recommendations:",
    ]
    for k, pred, m in scored[:5]:
        lines.append(f"- **{k}** → ~ **{pred:.1f}** attendees (event mult {m:.2f}x)")

    await ctx.send("\n".join(lines))

@bot.command(name="event_plan")
async def event_plan_cmd(ctx: commands.Context, *, args: str = ""):
    """Plan an event with a forecast + supplies + checklist.

    Usage:
      !event_plan <type>
      !event_plan <type> <YYYY-MM-DD>
      !event_plan <type> <context words...>
      !event_plan <type> <YYYY-MM-DD> <context words...>

    Notes:
      - This is the main planning hub (keeps the command list small).
      - PowerBot never sends automatic messages; this runs only when asked.
    """
    raw = (args or "").strip()
    if not raw:
        await ctx.send("Usage: `!event_plan <type> [YYYY-MM-DD] [context...]`")
        return

    parts = raw.split()
    event_type = parts[0]
    rest = parts[1:]

    # Optional date
    plan_date = None
    context_text = ""
    if rest:
        maybe_date = rest[0]
        try:
            if len(maybe_date) == 10 and maybe_date[4] == "-" and maybe_date[7] == "-":
                plan_date = datetime.fromisoformat(maybe_date).date()
                context_text = " ".join(rest[1:]).strip()
            else:
                context_text = " ".join(rest).strip()
        except Exception:
            context_text = " ".join(rest).strip()

    if plan_date is None:
        plan_date = get_next_monday()

    result = attendance_forecast(event_type, context_text or None, the_date=plan_date)
    acad = result.get("acad_info") or {}

    expected = float(result.get("expected", 0.0) or 0.0)
    low_90 = int(result.get("low_90", 0) or 0)
    high_90 = int(result.get("high_90", 0) or 0)
    base = float(result.get("base", 0.0) or 0.0)
    n = int(result.get("n", 0) or 0)
    under_prob = float(result.get("under_prob", 0.0) or 0.0)

    if under_prob < 0.2:
        risk = "Low"
    elif under_prob < 0.5:
        risk = "Medium"
    else:
        risk = "High"

    # Supplies defaults (simple + stable)
    et = event_type.lower().strip()
    supplies_lines = []
    if et == "food":
        per_person = 2
        core = expected * per_person
        buffer = core * 1.10
        supplies_lines.append(f"Assuming **{per_person} pieces/person**:")
        supplies_lines.append(f"• Core estimate: **{core:.0f}** pieces")
        supplies_lines.append(f"• +10% buffer: **{buffer:.0f}** pieces")
        supplies_lines.append("(Adjust for RSVPs + budget.)")
    else:
        supplies_lines.append("Use **expected attendance** as your baseline for supplies.")
        supplies_lines.append("Tip: If it’s hands-on (craft/materials), plan **1 per person** + ~10% buffer.")

    # Checklist
    steps = build_checklist_steps(event_type)
    checklist = []
    for i, step in enumerate(steps[:12], start=1):
        checklist.append(f"{i}. {step}")
    if len(steps) > 12:
        checklist.append(f"… +{len(steps) - 12} more")

    embed = discord.Embed(
        title=f"📝 Event Plan – {event_type.title()}",
        description=f"Date: **{plan_date.isoformat()}**" + (f" • Context: **{context_text}**" if context_text else ""),
        color=0x2A9D8F,
    )

    embed.add_field(
        name="📈 Forecast",
        value=(
            f"Members in model: **{n}**\n"
            f"Baseline: **{base:.1f}**\n"
            f"Expected: **{expected:.1f}**\n"
            f"Range (≈90%): **{low_90}–{high_90}**\n"
            f"Risk (below baseline): **{under_prob*100:.0f}%** → **{risk}**\n"f"Factors: event×{float(result.get('mult_event',1.0)):.2f} • history×{float(result.get('mult_history',1.0)):.2f} • learned×{float(result.get('mult_learned',1.0)):.2f} • weekday×{float(result.get('mult_weekday',1.0)):.2f} • calendar×{float(result.get('mult_calendar',1.0)):.2f} • fatigue×{float(result.get('mult_fatigue',1.0)):.2f} • marketing×{float(result.get('mult_marketing',1.0)):.2f} • context×{float(result.get('mult_context',1.0)):.2f}"
        ),
        inline=False,
    )

    if acad and isinstance(acad, dict) and acad.get("phase"):
        acad_lines = [
            f"Term: **{acad.get('term','?')}**",
            f"Phase: **{acad.get('phase','?')}**",
            f"Multiplier: **{float(acad.get('multiplier', 1.0)):.2f}×**",
        ]
        notes = acad.get("notes") or []
        for nline in notes[:3]:
            acad_lines.append(f"• {nline}")
        embed.add_field(name="📚 Academic Context", value="\n".join(acad_lines)[:1024], inline=False)


    # ---------------- Strategic additions (no new commands) ---------------- #
    similar_lines = []
    try:
        hist_events = load_events()
        matches = []
        for e in hist_events:
            if not isinstance(e, dict):
                continue
            if str(e.get("event_type","")).lower().strip() != et:
                continue
            att = e.get("attendance")
            if not isinstance(att, (int, float)) or att <= 0:
                continue
            matches.append(e)
        def _k(e: dict):
            return str(e.get("date") or e.get("created_at") or e.get("timestamp") or "")
        matches = sorted(matches, key=_k)
        recent = matches[-3:][::-1]
        if recent:
            vals = []
            for e in recent:
                name = e.get("name") or e.get("event_type") or "event"
                dt = str(e.get("date") or e.get("created_at") or "")[:10]
                att = int(e.get("attendance") or 0)
                vals.append(att)
                label = f"• {name}"
                if dt:
                    label += f" ({dt})"
                label += f": **{att}** attendees"
                similar_lines.append(label)
            avg_sim = sum(vals) / len(vals) if vals else None
            if avg_sim is not None:
                similar_lines.append(f"Average of similar: **{avg_sim:.1f}**")
    except Exception:
        similar_lines = []

    cost_lines = []
    try:
        db = get_db()
        hist_events = load_events()
        cpas = []
        for e in hist_events:
            if not isinstance(e, dict):
                continue
            if str(e.get("event_type","")).lower().strip() != et:
                continue
            eid = e.get("id")
            att = e.get("attendance")
            if eid is None or not isinstance(att, (int, float)) or att <= 0:
                continue
            if not db:
                continue
            cost = float(db.sum_expenses_for_event(int(eid)) or 0)
            if cost <= 0:
                continue
            cpas.append(cost / max(1.0, float(att)))
        if cpas:
            avg_cpa = sum(cpas) / len(cpas)
            est_total = avg_cpa * max(0.0, expected)
            cost_lines.append(f"- Estimated cost/attendee: **${avg_cpa:.2f}** (based on {len(cpas)} past events)")
            overall_cpas = []
            for e in hist_events:
                if not isinstance(e, dict):
                    continue
                eid = e.get("id")
                att = e.get("attendance")
                if eid is None or not isinstance(att, (int, float)) or att <= 0:
                    continue
                cost = float(db.sum_expenses_for_event(int(eid)) or 0)
                if cost <= 0:
                    continue
                overall_cpas.append(cost / max(1.0, float(att)))
            if overall_cpas and len(overall_cpas) >= 3:
                overall_avg = sum(overall_cpas) / len(overall_cpas)
                if avg_cpa >= overall_avg * 1.10:
                    comp = "Slightly higher than your overall average."
                elif avg_cpa <= overall_avg * 0.90:
                    comp = "Slightly lower than your overall average."
                else:
                    comp = "Close to your overall average."
                cost_lines.append(f"- Compared to past events: {comp}")
            cost_lines.append(f"- Estimated total cost for this plan: **~${est_total:,.0f}**")
    except Exception:
        cost_lines = []

    take_lines = []
    try:
        phase = str(acad.get("phase") or "").lower()
        if et == "food":
            take_lines.append("This type performs best when paired with clear promotion (IG countdown + Discord ping).")
        elif et in {"collab", "collaboration"}:
            take_lines.append("Collabs can overperform—lock details early and co-promote in both communities.")
        else:
            take_lines.append("Clarity beats complexity: clear theme + low-pressure structure tends to raise turnout.")

        if phase:
            if "final" in phase:
                take_lines.append("Finals phase usually suppresses turnout—plan low-cost and low-pressure.")
            elif "midterm" in phase:
                take_lines.append("Midterms may reduce turnout a bit—keep expectations realistic.")
    except Exception:
        take_lines = []

    if cost_lines:
        embed.add_field(name="💰 Cost Efficiency", value="\n".join(cost_lines)[:1024], inline=False)
    if similar_lines:
        embed.add_field(name="📊 Similar Events", value="\n".join(similar_lines)[:1024], inline=False)
    if take_lines:
        embed.add_field(name="🧠 PowerBot Take", value="\n".join(f"• {t}" for t in take_lines)[:1024], inline=False)

    try:
        _append_event_plan_log({
            "ts": datetime.now(timezone.utc).isoformat(),
            "user_id": str(getattr(ctx.author, "id", "")),
            "user_name": str(getattr(ctx.author, "name", getattr(ctx.author, "display_name", ""))),
            "event_type": et,
            "plan_date": plan_date.isoformat() if plan_date else None,
            "context": context_text,
            "expected": expected,
            "low_90": low_90,
            "high_90": high_90,
            "risk": risk,
            "acad_phase": acad.get("phase") if isinstance(acad, dict) else None,
        })
    except Exception:
        pass

    embed.add_field(name="🍱 Supplies", value="\n".join(supplies_lines)[:1024], inline=False)
    embed.add_field(name="✅ Checklist", value="\n".join(checklist)[:1024], inline=False)

    embed.add_field(
        name="➡️ Next",
        value=(
            "• `!budget` – check remaining funds\n"
            "• `!suggest_next_event` – pick the best event type for next Monday\n"
            "• `!expense ...` – log costs after purchase"
        ),
        inline=False,
    )

    await ctx.send(embed=embed)


# -------------- POWERBOT  — MERGED EVENT & PLANNING COMMANDS -------------- #

ANNOUNCEMENTS_CHANNEL_ID = 0  # set in your deployment if you want a hardcoded default


# ===== EVENT GROUP =====
# Usage:
#   !events rsvp <title>
#   !events rsvp_report <message_id> <event_id>

# -----------------------------
# Event Hub (command-with-subcommands)
# Keeps command list small while adding capabilities.
# -----------------------------

def _try_parse_ymd(s: str) -> date | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None



@bot.group(name="events", invoke_without_command=True)
async def events_group(ctx: commands.Context):
    """Event command hub (keeps the command list small)."""
    lines = [
        "🧩 **Events Hub**",
        "Use one of these:",
        "- `!events plan <type> [YYYY-MM-DD] [context...]`",
        "- `!events simulate <type> [YYYY-MM-DD] [context...]`",
        "- `!events promo <type> [YYYY-MM-DD]`",
        "- `!events review <event_id|name>`",
        "- `!events roi <event_id|name>`",
        "- `!events rsvp <title>`",
        "- `!events rsvp_report <message_id> <event_id>`",
        "",
        "Legacy: `!event_plan ...` still works (same as `!events plan`).",
    ]
    await ctx.send("\n".join(lines))


@events_group.command(name="plan")
async def event_plan_subcmd(ctx: commands.Context, event_type: str = "", date_or_context: str = "", *, context: str = ""):
    """Route to the existing !event_plan command."""
    parts = [p for p in [event_type, date_or_context, context] if p]
    arg_blob = " ".join(parts).strip()
    cmd = bot.get_command("event_plan")
    if cmd is None:
        await ctx.send("Missing `event_plan` command in this build.")
        return
    await ctx.invoke(cmd, args=arg_blob)


@events_group.command(name="simulate")
async def event_simulate_subcmd(ctx: commands.Context, event_type: str = "", date_or_context: str = "", *, context: str = ""):
    et = (event_type or "").strip()
    if not et:
        await ctx.send("Usage: `!events simulate <type> [YYYY-MM-DD] [context...]`")
        return
    dt = _try_parse_ymd(date_or_context)
    ctx_text = "" if dt else " ".join([date_or_context, context]).strip()
    if dt:
        ctx_text = (context or "").strip()

    base = smart_forecast_3(et, dt, ctx_text)

    weekday_scenarios=[]
    if dt is not None:
        def _shift_to(target_wd: int) -> date:
            cur = dt.weekday()
            forward = (target_wd - cur) % 7
            backward = forward - 7
            d1 = dt + timedelta(days=forward)
            d2 = dt + timedelta(days=backward)
            return d1 if abs((d1-dt).days) <= abs((d2-dt).days) else d2
        for label, wd in [("Tuesday",1),("Thursday",3)]:
            nd = _shift_to(wd)
            if nd != dt:
                weekday_scenarios.append((f"{label} swap → {nd.isoformat()}", nd))

    scenarios=[
        ("Base", base),
        ("+ food", smart_forecast_3(et, dt, (ctx_text + " food").strip())),
        ("+ prizes", smart_forecast_3(et, dt, (ctx_text + " prizes raffle").strip())),
        ("+ collab", smart_forecast_3(et, dt, (ctx_text + " collab collaboration").strip())),
        ("+ strong promo", smart_forecast_3(et, dt, (ctx_text + " instagram discord engage flyers").strip())),
    ]
    for label, nd in weekday_scenarios:
        scenarios.append((label, smart_forecast_3(et, nd, ctx_text)))

    lines=[f"🧪 **Scenario Simulator — {et}**"]
    if dt:
        lines.append(f"Target date: **{dt.isoformat()}** ({dt.strftime('%a')})")
    if ctx_text:
        lines.append(f"Context: {ctx_text}")
    lines.append("")
    lines.append("Estimated attendance (expected • range):")
    for label, res in scenarios:
        exp=float(res.get('expected',0)); low=float(res.get('low',0)); high=float(res.get('high',0))
        lines.append(f"- **{label}**: **{exp:.0f}** ( {low:.0f}–{high:.0f} )")

    # quick risk take
    base_exp = float(base.get('expected',0) or 0)
    best = max(scenarios, key=lambda x: float(x[1].get('expected',0) or 0))
    worst = min(scenarios, key=lambda x: float(x[1].get('expected',0) or 0))
    lines.append("")
    lines.append(f"Best lever: **{best[0]}** → **{float(best[1].get('expected',0)):.0f}**")
    lines.append(f"Biggest downside: **{worst[0]}** → **{float(worst[1].get('expected',0)):.0f}**")

    if bool(config.get('ai_enabled', True)):
        try:
            brief='\n'.join(lines[-min(14,len(lines)):])
            ai=await ai_generate_text(
                'Summarize which lever increases turnout most, mention one risk, and give one actionable next step.',
                system='You are a club operations analyst. Be concise. Do not invent numbers.',
                context=brief,
                max_tokens=260,
            )
            if ai:
                lines.append("")
                lines.append("🤖 **AI Take:**")
                lines.append(ai.strip())
        except Exception:
            pass

    msg='\n'.join(lines)
    if len(msg) > 1900:
        msg = msg[:1900] + '\n\n...(truncated)'
    await ctx.send(msg)


@events_group.command(name="promo")
async def event_promo_subcmd(ctx: commands.Context, event_type: str = "", date_str: str = ""):
    et=(event_type or '').strip()
    if not et:
        await ctx.send("Usage: `!events promo <type> [YYYY-MM-DD]`")
        return
    dt=_try_parse_ymd(date_str)
    lines=[f"📣 **Promo Plan — {et}**"]
    if dt:
        lines += [
            f"Event date: **{dt.isoformat()}**",
            "",
            "Timeline (suggested):",
            f"- {(dt - timedelta(days=7)).isoformat()} — Confirm Engage listing + details",
            f"- {(dt - timedelta(days=5)).isoformat()} — Instagram post (main graphic)",
            f"- {(dt - timedelta(days=4)).isoformat()} — Flyers up in high-traffic spots",
            f"- {(dt - timedelta(days=2)).isoformat()} — Discord ping + IG story countdown",
            f"- {(dt - timedelta(days=1)).isoformat()} — Story reminder + short Discord bump",
            f"- {dt.isoformat()} — Day-of story / clip + last reminder",
        ]
    else:
        lines += [
            "Tip: add a date for a full timeline, e.g. `!events promo game 2026-03-12`",
            "",
            "Baseline plan:",
            "- Engage listing ~7 days before",
            "- Instagram post ~5 days before",
            "- Flyers ~4 days before",
            "- Discord ping ~2 days before + day-before reminder",
        ]
    await ctx.send('\n'.join(lines))


@events_group.command(name="review")
async def event_review_subcmd(ctx: commands.Context, *, query: str = ""):
    events = load_events()
    ev = _find_event_by_query(events, query)
    if not ev:
        await ctx.send("Couldn't find that event in `events.json`. Try `!club full` to see recent names/ids.")
        return
    db = get_db()
    metrics = _event_success_score(ev, db)
    name = metrics['name']
    dt = str(ev.get('date') or ev.get('created_at') or ev.get('timestamp') or '')[:10]
    lines=[f"📝 **Post-Event Review — {name}**"]
    if dt:
        lines.append(f"Date: {dt}")
    if isinstance(metrics.get('attendance'), (int,float)):
        lines.append(f"Actual attendance: **{int(metrics['attendance'])}**")
    if isinstance(metrics.get('expected'), (int,float)):
        lines.append(f"Expected (model): **{float(metrics['expected']):.0f}**")
    if isinstance(metrics.get('delta_pct'), (int,float)):
        lines.append(f"Performance vs expected: **{float(metrics['delta_pct'])*100:+.0f}%**")
    if isinstance(metrics.get('cost_per_attendee'), (int,float)):
        lines.append(f"Cost per attendee: **${float(metrics['cost_per_attendee']):.2f}**")
    if isinstance(metrics.get('success_score'), (int,float)):
        lines.append(f"Success score: **{float(metrics['success_score']):.1f}/10**")

    if bool(config.get('ai_enabled', True)):
        try:
            ai=await ai_generate_text(
                'Give 2 plausible reasons for the result and 2 specific improvements next time. Do not invent facts.',
                system='You are a club operations analyst. Be concise and practical.',
                context='\n'.join(lines),
                max_tokens=260,
            )
            if ai:
                lines.append('')
                lines.append('🤖 **AI Notes:**')
                lines.append(ai.strip())
        except Exception:
            pass

    msg='\n'.join(lines)
    if len(msg) > 1900:
        msg = msg[:1900] + '\n\n...(truncated)'
    await ctx.send(msg)


@events_group.command(name="roi")
async def event_roi_subcmd(ctx: commands.Context, *, query: str = ""):
    events = load_events()
    ev = _find_event_by_query(events, query)
    if not ev:
        await ctx.send("Couldn't find that event in `events.json`. Try `!club full` for recent names/ids.")
        return
    db = get_db()
    m = _event_success_score(ev, db)
    lines=[f"💸 **Event ROI — {m['name']}**"]
    if isinstance(m.get('attendance'), (int,float)):
        lines.append(f"Attendance: **{int(m['attendance'])}**")
    if isinstance(m.get('cost'), (int,float)):
        lines.append(f"Cost: **${float(m['cost']):.2f}**")
    else:
        lines.append("Cost: (not linked yet)")
    if isinstance(m.get('cost_per_attendee'), (int,float)):
        cpa=float(m['cost_per_attendee'])
        lines.append(f"Cost per attendee: **${cpa:.2f}**")
        tag = '🔥 excellent' if cpa <= 2 else ('✅ solid' if cpa <= 5 else '⚠️ pricey')
        lines.append(f"Efficiency: {tag}")
    if isinstance(m.get('success_score'), (int,float)):
        lines.append(f"Success score: **{float(m['success_score']):.1f}/10**")
    await ctx.send('\n'.join(lines))


@events_group.command(name="rsvp")
async def event_rsvp(ctx: commands.Context, *, title: str):
    channel = ctx.guild.get_channel(ANNOUNCEMENTS_CHANNEL_ID) if ctx.guild else None
    if channel is None:
        channel = bot.get_channel(ANNOUNCEMENTS_CHANNEL_ID)
    if channel is None:
        await ctx.send(f"I couldn't find the announcements channel (ID: {ANNOUNCEMENTS_CHANNEL_ID}). Check the ID in the code.")
        return
    embed = discord.Embed(
        title=f"📢 {title}",
        description=(
            "React with ✅ if you're **coming** and ❔ if you're **maybe**.\n"
            "You can change your reaction later if your plans change!"
        ),
        color=0x00B4D8,
    )
    embed.set_footer(text='PowerBot – RSVP')
    rsvp_message = await channel.send(embed=embed)
    try:
        await rsvp_message.add_reaction('✅')
        await rsvp_message.add_reaction('❔')
    except discord.HTTPException:
        await ctx.send("I posted the RSVP, but couldn't add reactions automatically.")
    if channel.id != ctx.channel.id:
        await ctx.send(f"RSVP for **{title}** posted in {channel.mention} with ✅ / ❔ reactions.")


@events_group.command(name="rsvp_report")
async def event_rsvp_report(ctx: commands.Context, message_id: int, event_id: int):
    try:
        rsvp_msg = await ctx.channel.fetch_message(message_id)
    except discord.NotFound:
        await ctx.send("I couldn't find a message with that ID in this channel.")
        return
    except discord.HTTPException:
        await ctx.send("Discord had an issue fetching that message. Try again.")
        return
    going = 0; maybe = 0
    for reaction in rsvp_msg.reactions:
        if str(reaction.emoji) == '✅':
            going = reaction.count - 1
        elif str(reaction.emoji) == '❔':
            maybe = reaction.count - 1
    events = load_events()
    event = next((e for e in events if e.get('id') == event_id), None)
    if event is None:
        await ctx.send(f"No event found with id #{event_id}. Use `!events` to see IDs.")
        return
    actual = event.get('attendance', 0)
    etype = event.get('event_type', 'unknown')
    ts = event.get('timestamp', '')
    date_str = ts.split('T')[0] if ts else 'unknown-date'
    total_rsvp = max(0, going)
    diff = actual - total_rsvp
    if total_rsvp == 0:
        ratio_line = 'No ✅ RSVPs recorded (people may have just shown up).'
    else:
        ratio = (actual / total_rsvp) * 100
        ratio_line = f"Actual was **{ratio:.1f}%** of the ✅ count."
    if diff > 0:
        diff_text = f"Actual attendance was **{diff}** higher than ✅ RSVPs."
    elif diff < 0:
        diff_text = f"Actual attendance was **{abs(diff)}** lower than ✅ RSVPs."
    else:
        diff_text = 'Actual attendance matched the ✅ RSVP count exactly.'
    lines=[
        f"📊 RSVP Report for event **#{event_id}** ({etype}) on **{date_str}**",
        '',
        f"- ✅ Coming: **{max(0, going)}**",
        f"- ❔ Maybe: **{max(0, maybe)}**",
        f"- Logged attendance: **{actual}**",
        '',
        ratio_line,
        diff_text,
    ]
    await ctx.send('\n'.join(lines))



@bot.group(name="plan")
async def plan_group(ctx: commands.Context):
    """
    Group for planning utilities (suggest what to run, compare types, etc.).
    """
    if ctx.invoked_subcommand is None:
        await ctx.send(
            "Planning commands:\n"
            "`!plan suggest` – Suggest an event type for next Monday\n"
            "`!plan compare <type1> <type2>` – Compare two event types"
        )


@plan_group.command(name="suggest")
async def plan_suggest_next_event(ctx: commands.Context):
    """
    Suggest an event type for the next Monday meeting based on:
    - Logged averages
    - Event type multipliers
    - Recency (avoid repeating the same thing)
    - Academic calendar phase

    Replaces `!suggest_next_event`.
    """
    events = load_events()
    next_mon = get_next_monday()
    acad = get_academic_context(next_mon)

    # Compute per-type averages
    type_avgs: dict[str, float] = {}
    if events:
        counts: dict[str, list[int]] = {}
        for e in events:
            et = e.get("event_type", "unknown").lower()
            counts.setdefault(et, []).append(e.get("attendance", 0))
        for et, vals in counts.items():
            type_avgs[et] = sum(vals) / len(vals)

    # How recently each type was used (in days)
    recency_days: dict[str, int] = {}
    if events:
        for e in events:
            et = e.get("event_type", "unknown").lower()
            try:
                ts = datetime.fromisoformat(e["timestamp"]).date()
            except Exception:
                continue
            age = (next_mon - ts).days
            if et not in recency_days or age < recency_days[et]:
                recency_days[et] = age

    candidates = CLUB_MEMORY["event_types"]
    base_att = config.get("base_attendance", CLUB_MEMORY.get("baseline_attendance_default", 15))

    scores: dict[str, float] = {}
    reasoning: dict[str, list[str]] = {}

    for et in candidates:
        et_lower = et.lower()
        lines: list[str] = []

        avg = type_avgs.get(et_lower, base_att)
        mult = EVENT_TYPE_MULTIPLIERS.get(et_lower, 1.0)

        score = avg * mult
        lines.append(f"Base from logs/model: avg≈{avg:.1f}, mult×{mult:.2f} → {score:.1f}")

        # Recency penalty/bonus
        days_since = recency_days.get(et_lower)
        if days_since is not None:
            if days_since <= 7:
                score *= 0.7
                lines.append(f"Recently used ({days_since} days ago) → penalty applied.")
            elif days_since <= 21:
                lines.append(f"Used {days_since} days ago → neutral.")
            else:
                score *= 1.1
                lines.append(f"Not used for {days_since} days → small bonus.")
        else:
            score *= 1.05
            lines.append("No logged data yet → small bonus for trying it.")

        # Academic calendar influence
        if "Finals" in acad["phase"] and et_lower == "food":
            score *= 0.9
            lines.append("Finals period: big food events are a bit risky → slight down-weight.")
        elif "Early Semester" in acad["phase"] and et_lower in ("trivia", "food", "karaoke"):
            score *= 1.1
            lines.append("Early semester: flashy events perform well → bonus.")
        elif "Break" in acad["phase"] and et_lower not in ("regular", "chill"):
            score *= 0.8
            lines.append("Break period: fancy events less effective → small penalty.")

        scores[et_lower] = score
        reasoning[et_lower] = lines

    best_type = max(scores, key=scores.get)
    best_score = scores[best_type]

    lines_out: list[str] = [
        f"🧠 Suggestion for next Monday (**{next_mon.isoformat()}**):",
        f"- Recommended event type: **{best_type}**",
        "",
        "📚 Academic context:",
        f"- Term: {acad['term']}",
        f"- Phase: {acad['phase']}",
        f"- Calendar multiplier baseline: {acad['multiplier']:.2f}x",
        "",
        "📊 Why this type:",
    ]
    lines_out.extend(f"- {ln}" for ln in reasoning[best_type])

    lines_out.append("")
    lines_out.append("All type scores (higher = better fit right now):")
    for et_lower, sc in sorted(scores.items(), key=lambda kv: kv[1], reverse=True):
        lines_out.append(f"- {et_lower}: {sc:.1f}")

    msg = "\n".join(lines_out)
    if len(msg) > 1900:
        msg = msg[:1900] + "\n\n...(truncated)"
    await ctx.send(msg)


@plan_group.command(name="compare")
async def plan_compare(ctx: commands.Context, type1: str, type2: str):
    """
    Compare two event types using logs + model patterns.
    Replaces `!compare`.
    Usage: !plan compare <type1> <type2>
    """
    t1 = type1.lower()
    t2 = type2.lower()

    events = load_events()
    type_avgs: dict[str, float] = {}

    if events:
        counts: dict[str, list[int]] = {}
        for e in events:
            et = e.get("event_type", "unknown")
            counts.setdefault(et, []).append(e.get("attendance", 0))
        for et, vals in counts.items():
            type_avgs[et] = sum(vals) / len(vals)

    def describe_type(et: str) -> list[str]:
        lines = [f"**{et}**"]
        avg = type_avgs.get(et)
        if avg is not None:
            lines.append(f"- Logged average attendance: **{avg:.1f}**")
        else:
            lines.append("- No logged data yet; using only general patterns.")
        pat = CLUB_MEMORY["patterns"].get(et)
        if pat:
            lines.append(f"- Pattern: {pat}")
        mult = EVENT_TYPE_MULTIPLIERS.get(et, 1.0)
        lines.append(f"- Attendance multiplier in model: **×{mult:.2f}**")
        return lines

    lines: list[str] = []
    lines.append(f"⚖️ Comparing **{t1}** vs **{t2}**:")
    lines.append("")

    lines.extend(describe_type(t1))
    lines.append("")
    lines.extend(describe_type(t2))

    avg1 = type_avgs.get(t1)
    avg2 = type_avgs.get(t2)
    if avg1 is not None and avg2 is not None:
        lines.append("")
        if avg1 > avg2:
            lines.append(
                f"📌 Based on your logs, **{t1}** tends to draw more people than **{t2}** "
                f"by about {avg1 - avg2:.1f} attendees on average."
            )
        elif avg2 > avg1:
            lines.append(
                f"📌 Based on your logs, **{t2}** tends to draw more people than **{t1}** "
                f"by about {avg2 - avg1:.1f} attendees on average."
            )
        else:
            lines.append("📌 Both event types currently have about the same average attendance.")
    else:
        lines.append("")
        lines.append(
            "📌 You don't have complete logged data for both types yet, so this comparison relies more on general patterns."
        )

    msg = "\n".join(lines)
    if len(msg) > 1900:
        msg = msg[:1900] + "\n\n...(truncated)"
    await ctx.send(msg)


# ----------------- SETTINGS --------------------- #

@bot.command(name="set_base")
async def set_base_cmd(ctx: commands.Context, value: int):
    config["base_attendance"] = value
    save_config(config)
    await ctx.send(f"Baseline non-food attendance updated to {value}.")


@bot.command(name="set_members")
async def set_members_cmd(ctx: commands.Context, value: int):
    config["total_members"] = value
    save_config(config)
    try:
        db = get_db()
        if db:
            db.log_member_count(total_members=int(value), source="manual", logged_by=str(ctx.author))
    except Exception:
        pass
    await ctx.send(f"Total members in the model updated to {value}.")



@bot.command(name="club")
async def club_cmd(ctx: commands.Context, *, mode: str = ""):
    """Club analytics dashboard.

    Modes:
      !club
      !club full
      !club insights
      !club finances
      !club momentum
      !club semester
    """
    if not (is_eboard(getattr(ctx, 'author', None)) or _is_owner(getattr(ctx, "author", None))):
        await ctx.send("⛔ This command is limited to **E-board**.")
        return

    mode = (mode or '').strip().lower()
    detail = mode in {'full','detail','detailed'}
    cfg = get_config()
    db = get_db()
    events = load_events()
    valid = [e for e in events if isinstance(e, dict) and isinstance(e.get('attendance'), (int,float)) and (e.get('attendance') or 0) > 0]

    def _event_sort_key(e: dict):
        return e.get('date') or e.get('created_at') or e.get('timestamp') or ''
    sorted_valid = sorted(valid, key=_event_sort_key)

    avg_attendance = (sum(float(e.get('attendance') or 0) for e in valid) / len(valid)) if valid else None
    latest_members = None
    if db:
        try:
            latest_members = db.latest_member_count()
        except Exception:
            latest_members = None
    total_members = latest_members or cfg.get('total_members')
    total_budget = float(cfg.get('budget_total') or 0)
    spent = 0.0
    if db:
        try:
            spent = float(db.sum_expenses())
        except Exception:
            spent = 0.0
    remaining = total_budget - spent

    momentum = _momentum_metrics(sorted_valid)
    diversity = _diversity_metrics(sorted_valid)
    retention = _retention_metrics(sorted_valid)
    marketing = _marketing_metrics(sorted_valid)
    collab = _collab_metrics(sorted_valid)
    budget_plan = _budget_plan_metrics(sorted_valid, cfg, db)

    learned = load_learned_patterns() or update_learned_patterns(force=False)
    tu = learned.get('type_uplift', {}) if isinstance(learned, dict) else {}
    sig = learned.get('signals', {}) if isinstance(learned, dict) else {}

    if mode == 'momentum':
        lines=['📈 **Club Momentum**']
        if avg_attendance is not None:
            lines.append(f"Average attendance: **{avg_attendance:.1f}**")
        if momentum.get('available'):
            lines.append(f"Recent events: {' → '.join(str(int(v)) for v in momentum.get('recent', []))}")
            gp = momentum.get('growth_pct')
            if isinstance(gp, (int,float)):
                lines.append(f"Momentum: **{gp:+.0f}%** (last block vs previous)")
            proj = momentum.get('projected_next')
            if isinstance(proj, (int,float)):
                lines.append(f"Projected next event: **~{proj:.0f} attendees**")
        else:
            lines.append('Not enough attendance history yet.')
        if diversity.get('available'):
            lines.append(f"Variety score: **{diversity.get('variety_score')}**")
        await ctx.send('\n'.join(lines))
        return

    if mode == 'finances':
        lines=['💴 **Club Finances**', f"Total budget: **${total_budget:,.2f}**", f"Spent: **${spent:,.2f}**", f"Remaining: **${remaining:,.2f}**"]
        costs=[]
        for e in sorted_valid:
            c=_event_cost_value(e, db)
            a=e.get('attendance')
            if isinstance(c,(int,float)) and isinstance(a,(int,float)) and a>0:
                costs.append(float(c)/float(a))
        if costs:
            lines.append(f"Avg cost per attendee: **${(sum(costs)/len(costs)):.2f}**")
        if budget_plan.get('avg_cost_by_type'):
            top=sorted(budget_plan['avg_cost_by_type'].items(), key=lambda kv: kv[1])[:4]
            lines.append('')
            lines.append('Cheapest event types (avg cost):')
            for et, c in top:
                lines.append(f"- **{et}**: **${c:.0f}**")
        if total_budget > 0 and remaining > 0:
            lines.append('')
            lines.append('Suggested allocation:')
            lines.append(f"- 1 major food event budget cap: **${min(max(remaining*0.35, 0), remaining):.0f}**")
            lines.append(f"- 2 low-cost engagement events combined: **${min(max(remaining*0.25, 0), remaining):.0f}**")
            lines.append(f"- Reserve / buffer: **${max(0, remaining*0.20):.0f}**")
        await ctx.send('\n'.join(lines)[:1900])
        return

    if mode == 'semester':
        lines=['🗓️ **Semester Snapshot**']
        if avg_attendance is not None:
            lines.append(f"Average attendance so far: **{avg_attendance:.1f}**")
        if momentum.get('available') and isinstance(momentum.get('projected_next'), (int,float)):
            proj = float(momentum['projected_next'])
            remaining_events = 4
            lines.append(f"Projected next event: **~{proj:.0f}**")
            lines.append(f"Projected next {remaining_events} events total: **~{proj*remaining_events:.0f}**")
        if isinstance(tu, dict) and tu:
            top=sorted([(float(v),k) for k,v in tu.items()], reverse=True)[:3]
            lines.append('')
            lines.append('Top event-type uplifts:')
            for v,k in top:
                lines.append(f"- **{k}**: ×{v:.2f}")
        if diversity.get('available'):
            lines.append(f"Variety score: **{diversity.get('variety_score')}**")
        await ctx.send('\n'.join(lines)[:1900])
        return

    if mode == 'insights':
        lines=['🧠 **Club Insights**']
        by_type={}
        for e in sorted_valid:
            sc = _event_success_score(e, db)
            if isinstance(sc.get('success_score'), (int,float)):
                by_type.setdefault(sc['event_type'], []).append(float(sc['success_score']))
        if by_type:
            ranked=sorted([(sum(v)/len(v), k, len(v)) for k,v in by_type.items()], reverse=True)[:5]
            lines.append('Best performing event types:')
            for avg,k,n in ranked:
                lines.append(f"- **{k}**: **{avg:.1f}/10** (n={n})")
            lines.append('')
        if diversity.get('available'):
            lines.append(f"Event diversity: **{diversity.get('variety_score')}**")
            lines.append(f"Most repeated recent type: **{diversity.get('most_repeated')}**")
        if retention.get('available'):
            lines.append(f"Retention: **{retention.get('retention_rate'):.0f}%** ({retention.get('returning')} returning / {retention.get('new')} new)")
        else:
            lines.append('Retention: add participant rosters to events.json to track returning members.')
        if marketing.get('available'):
            hu = marketing.get('high_uplift_pct')
            mu = marketing.get('mid_uplift_pct')
            if isinstance(hu, (int,float)):
                lines.append(f"Strong promo uplift: **{hu:+.0f}%** vs low-promo events")
            elif isinstance(mu, (int,float)):
                lines.append(f"Mid promo uplift: **{mu:+.0f}%** vs low-promo events")
            else:
                lines.append('Marketing: tracking available, but not enough contrast yet.')
        else:
            lines.append('Marketing impact: add `promotion_channels` / `promo_strength` into event entries for tracking.')
        if collab.get('available'):
            lines.append(f"Collab uplift: **{collab.get('uplift_pct'):+.0f}%** vs solo events")
        else:
            lines.append('Collab impact: log `collab: true` or partner club fields to track this.')
        if momentum.get('available') and isinstance(momentum.get('growth_pct'), (int,float)):
            lines.append(f"Momentum: **{momentum.get('growth_pct'):+.0f}%**")
        if bool(cfg.get('ai_enabled', True)):
            try:
                ai = await ai_generate_text(
                    'Summarize the most important 3 strategic takeaways for the club leadership based on these metrics. Do not invent numbers.',
                    system='You are a club operations strategist. Be concise, practical, and grounded in the provided metrics.',
                    context='\n'.join(lines),
                    max_tokens=260,
                )
                if ai:
                    lines.append('')
                    lines.append('🤖 **AI Summary:**')
                    lines.append(ai.strip())
            except Exception:
                pass
        await ctx.send('\n'.join(lines)[:1900])
        return

    embed_title = 'PowerBot – Snapshot'
    if isinstance(CLUB_MEMORY, dict) and CLUB_MEMORY.get('club_name'):
        embed_title = f"🇯🇵 {CLUB_MEMORY['club_name']} – Snapshot"
    desc = f"School: **{CLUB_MEMORY.get('university')}**" if isinstance(CLUB_MEMORY, dict) and CLUB_MEMORY.get('university') else ''
    embed = discord.Embed(title=embed_title, description=desc, color=0x2A9D8F)

    if total_members:
        embed.add_field(name='👥 Members', value=f"Model total: **{int(total_members)}**", inline=False)
    embed.add_field(name='💴 Budget', value=f"Total: **${total_budget:,.2f}**\nSpent: **${spent:,.2f}**\nRemaining: **${remaining:,.2f}**", inline=False)

    att_lines=[]
    if avg_attendance is not None:
        att_lines.append(f"Avg attendance: **{avg_attendance:.1f}**")
    if momentum.get('available'):
        att_lines.append("Recent: " + ' → '.join(str(int(v)) for v in momentum.get('recent', [])))
        gp = momentum.get('growth_pct')
        if isinstance(gp, (int,float)):
            att_lines.append(f"Momentum: **{gp:+.0f}%**")
    if att_lines:
        embed.add_field(name='📊 Attendance', value='\n'.join(att_lines)[:1024], inline=False)

    grade='B'; notes=[]
    if avg_attendance is None:
        grade='C'; notes.append('Log attendance for more accurate scoring.')
    else:
        baseline=float(cfg.get('base_attendance') or avg_attendance)
        ratio=avg_attendance/max(1.0, baseline)
        grade='A' if ratio >= 1.15 else ('B+' if ratio >= 1.0 else ('B' if ratio >= 0.9 else ('C+' if ratio >= 0.8 else 'C')))
        if diversity.get('available') and diversity.get('variety_score') == 'Low':
            notes.append('Variety is low—rotate event types soon.')
        if isinstance(collab.get('uplift_pct'), (int,float)) and collab.get('uplift_pct') > 10:
            notes.append('Collabs are helping—use them strategically.')
    health_lines=[f"Overall grade: **{grade}**"] + [f"• {n}" for n in notes[:3]]
    embed.add_field(name='🧭 Club Health', value='\n'.join(health_lines)[:1024], inline=False)

    extra=[]
    if diversity.get('available'):
        extra.append(f"Variety: **{diversity.get('variety_score')}**")
    if retention.get('available'):
        extra.append(f"Retention: **{retention.get('retention_rate'):.0f}%**")
    if isinstance(collab.get('uplift_pct'), (int,float)):
        extra.append(f"Collab uplift: **{collab.get('uplift_pct'):+.0f}%**")
    if extra:
        embed.add_field(name='📈 Extra Analytics', value='\n'.join(f"• {x}" for x in extra)[:1024], inline=False)

    try:
        tu = learned.get('type_uplift', {}) if isinstance(learned, dict) else {}
        sig = learned.get('signals', {}) if isinstance(learned, dict) else {}
        lp=[]
        if isinstance(tu, dict) and tu:
            top=sorted([(float(v),k) for k,v in tu.items()], reverse=True)[:3]
            lp.append('Top type uplifts:')
            for v,k in top:
                lp.append(f"• {k}: ×{v:.2f}")
        if isinstance(sig, dict) and sig:
            for k in ['food','collab','prizes','strong_promo']:
                if k in sig:
                    lp.append(f"• {k}: ×{float(sig[k]):.2f}")
        if lp:
            embed.add_field(name='🧠 Learned Patterns', value='\n'.join(lp)[:1024], inline=False)
    except Exception:
        pass

    try:
        next_mon=get_next_monday(); info=get_academic_context(next_mon)
        embed.add_field(name='📅 Next Monday', value=(f"Date: **{next_mon.isoformat()}**\nPhase: **{info.get('phase')}**\nRecommended multiplier: **{float(info.get('multiplier',1.0)):.2f}x**\nTip: Run `!event_plan <type>` or `!events plan <type>`."), inline=False)
    except Exception:
        pass

    if detail and sorted_valid:
        lines=[]
        for e in sorted_valid[-5:][::-1]:
            name=e.get('name') or e.get('event_type') or 'event'
            dt=e.get('date') or str(e.get('timestamp') or '')[:10]
            att=e.get('attendance')
            c=_event_cost_value(e, db)
            cstr=''
            if isinstance(c, (int,float)) and isinstance(att, (int,float)) and att > 0:
                cstr=f" • ${float(c):,.0f} (~${float(c)/float(att):.2f}/att)"
            elif isinstance(c, (int,float)):
                cstr=f" • ${float(c):,.0f}"
            lines.append(f"• **{name}** {('(' + dt + ')') if dt else ''}: **{int(att)}**{cstr}")
        embed.add_field(name='🗂 Recent events (last 5)', value='\n'.join(lines)[:1024], inline=False)

    await ctx.send(embed=embed)



@bot.command(name="health", aliases=["diag"])
async def health_cmd(ctx: commands.Context):
    """Internal health check: version, DB, AI status, backups, and basic counts."""
    if not (is_eboard(getattr(ctx, "author", None)) or _is_owner(getattr(ctx, "author", None))):
        await ctx.send("⛔ This command is limited to **E-board**.")
        return

    cfg = get_config()
    db = get_db()
    stats = {}
    if db:
        try:
            stats = db.stats()
        except Exception:
            stats = {}

    events = load_events()
    n_events = len(events) if events else 0

    # Backups status
    backup_count = 0
    latest_backup = "none"
    try:
        bdir = Path(BACKUP_DIR)
        if bdir.exists():
            files = sorted(bdir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
            backup_count = len(files)
            latest_backup = files[0].name if files else "none"
    except Exception:
        pass

    lines: list[str] = []
    lines.append("🩺 **PowerBot Health Check**")
    lines.append(f"- Version: **{POWERBOT_VERSION}**")
    lines.append(f"- DB path: `{DB_PATH}`")
    lines.append(f"- DB connected: **{bool(db)}**")
    lines.append(f"- Events logged (events.json): **{n_events}**")

    if stats:
        lines.append(f"- Interactions logged: **{stats.get('interactions', 0)}**")
        lines.append(f"- Attendance rows: **{stats.get('attendance_rows', 0)}**")
        lines.append(f"- Expense rows: **{stats.get('expense_rows', 0)}**")
        lines.append(f"- Member count rows: **{stats.get('member_count_rows', 0)}**")

    lines.append(f"- Activity tracking: **{bool(cfg.get('activity_tracking_enabled', True))}**")
    lines.append(f"- Backups stored: **{backup_count}** (latest: `{latest_backup}`)")
    lines.append(f"- Extensions loaded: **{_PB_EXTENSIONS_LOADED}**")
    lines.append(f"- AI enabled (config): **{AI_ENABLED}**")
    lines.append(f"- AI available: **{AI_AVAILABLE}**")
    lines.append(f"- AI backend: `{AI_BACKEND_INFO}`")
    lines.append(f"- AI model: `{AI_MODEL}`")

    await ctx.send("\n".join(lines))

@bot.command(name="budget")
async def budget_cmd(ctx: commands.Context, total: str | None = None):
    """Show budget snapshot. Use `!budget 7000` to set the total budget."""
    # E-board (or owner) only.
    if not (is_eboard(getattr(ctx, "author", None)) or _is_owner(getattr(ctx, "author", None))):
        await ctx.send("⛔ This command is limited to **E-board**.")
        return

    if total is not None:
        try:
            config["budget_total"] = float(total)
            save_config(config)
        except ValueError:
            await ctx.send("Usage: `!budget` or `!budget 7000`")
            return

    db = get_db()
    spent = db.sum_expenses() if db else 0.0
    total_budget = float(config.get("budget_total") or 0)
    remaining = total_budget - spent

    lines = [
        "💴 **Budget Snapshot**",
        f"- Total: ${total_budget:,.2f}",
        f"- Spent: ${spent:,.2f}",
        f"- Remaining: ${remaining:,.2f}",
    ]

    # --- Budget intelligence (no new commands) ---
    avg_cost_per_event = None
    est_events_remaining = None
    food_heavy_note = None
    try:
        events = load_events()
        if db and events:
            costs = []
            for e in events:
                if not isinstance(e, dict):
                    continue
                eid = e.get("id")
                if eid is None:
                    continue
                c = float(db.sum_expenses_for_event(int(eid)) or 0)
                if c > 0:
                    costs.append(c)
            if costs:
                avg_cost_per_event = sum(costs) / len(costs)
                if avg_cost_per_event > 0:
                    est_events_remaining = remaining / avg_cost_per_event

        if db:
            recent50 = db.recent_expenses(limit=50)
            if recent50:
                total_recent = 0.0
                food_recent = 0.0
                for r in recent50:
                    amt = float((r or {}).get("amount") or 0)
                    cat = str((r or {}).get("category") or "").lower().strip()
                    total_recent += amt
                    if "food" in cat or "snack" in cat or "drink" in cat:
                        food_recent += amt
                if total_recent > 0 and (food_recent / total_recent) >= 0.55:
                    food_heavy_note = f"⚠️ Recent spend is **food-heavy** (~{(food_recent/total_recent)*100:.0f}% of last 50 expenses)."
    except Exception:
        pass

    if avg_cost_per_event is not None:
        lines.append(f"- Avg cost per logged event: **${avg_cost_per_event:,.2f}**")
    if est_events_remaining is not None:
        lines.append(f"- Estimated events remaining at this pace: **~{est_events_remaining:.0f}**")
    if food_heavy_note:
        lines.append(f"- {food_heavy_note}")

    if db:
        recent = db.recent_expenses(limit=5)
        if recent:
            lines.append("")
            lines.append("🧾 **Recent expenses**")
            for r in recent:
                amt = float(r.get("amount") or 0)
                cat = (r.get("category") or "misc").strip()
                note = (r.get("note") or "").strip()
                lines.append(f"- ${amt:.2f} • {cat} • {note}".rstrip(" •"))

    await ctx.send("\n".join(lines))


@bot.command(name="expense", aliases=["spend"])
async def expense_cmd(ctx: commands.Context, amount: str, category: str = "misc", *, note: str = ""):
    """Log an expense.

    Examples:
    - `!expense 54.20 food kfc buckets`
    - `!expense 85 food event=12 KFC + drinks`
    """
    if not (is_eboard(getattr(ctx, "author", None)) or _is_owner(getattr(ctx, "author", None))):
        await ctx.send("⛔ This command is limited to **E-board**.")
        return

    try:
        amt = float(amount)
    except ValueError:
        await ctx.send("Usage: `!expense 54.20 food [event=<id>] <note>`")
        return

    # Optional event linkage: parse event=12 / eid=12
    event_id = None
    note_txt = (note or "").strip()
    m = re.search(r"(?:^|\s)(?:event|eid)\s*=\s*(\d+)", note_txt, re.IGNORECASE)
    if m:
        try:
            event_id = int(m.group(1))
        except Exception:
            event_id = None
        # Remove token from note
        note_txt = re.sub(r"(?:^|\s)(?:event|eid)\s*=\s*\d+", " ", note_txt, flags=re.IGNORECASE).strip()

    db = get_db()
    if not db:
        await ctx.send("SQLite DB is not initialized.")
        return

    db.log_expense(amount=amt, category=category, note=note_txt, event_id=event_id, logged_by=str(ctx.author))
    extra = f" (event #{event_id})" if event_id is not None else ""
    await ctx.send(f"✅ Logged expense{extra}: ${amt:.2f} • {category} • {note_txt or '(no note)'}")



# ---------------- 
# ============================================================
# AI HELPERS (ON-DEMAND, NO AUTO-CHAT)
# ============================================================

def _ensure_ai_ready(ctx: commands.Context) -> bool:
    if not AI_ENABLED:
        return False
    if not AI_AVAILABLE:
        return False
    return True

async def ai_generate_text(
    user_text: str,
    *,
    system: str = '',
    context: str = '',
    max_tokens: int = AI_MAX_TOKENS,
    force: bool = False,
) -> str | None:
    """Call the configured AI backend and return assistant text, or None on failure.

    Notes:
    - `force=True` lets owner-only DM AI work even if AI_ENABLED is off.
    - Default backend is local Ollama (no key). If unavailable, returns None.
    """
    # Lazy-refresh probe so starting Ollama after boot works without restart.
    global AI_AVAILABLE, AI_BACKEND_INFO, AI_LAST_ERROR, AI_LAST_ERROR_DETAIL
    AI_LAST_ERROR = ""
    AI_LAST_ERROR_DETAIL = ""
    if AI_BACKEND == "ollama" and not AI_AVAILABLE:
        ok, ver = _probe_ollama(OLLAMA_HOST)
        AI_AVAILABLE = bool(ok)
        AI_BACKEND_INFO = f"ollama{(' ' + ver) if ver else ''}".strip() if AI_AVAILABLE else "ollama (down)"
    if AI_BACKEND in ("none", "off", "disabled"):
        return None
    if not (AI_ENABLED or force):
        return None

    ctx_blob = (context or '').strip()
    if len(ctx_blob) > 8000:
        ctx_blob = ctx_blob[:8000] + '\n... (truncated)'

    async def _attempt(ctx: str, tokens: int, timeout_s: int) -> str | None:
        system_prompt = system or _build_ai_system_prompt()
        messages = [{'role': 'system', 'content': system_prompt}]
        if ctx:
            messages.append({'role': 'system', 'content': f'Context:\n{ctx}'})
        messages.append({'role': 'user', 'content': user_text})

        if AI_BACKEND != "ollama":
            return None

        url = f"{OLLAMA_HOST}/api/chat"
        payload = {
            "model": AI_MODEL,
            "messages": messages,
            "stream": False,
            "options": {
                "num_predict": max(64, min(int(tokens), 1500)),
            },
        }

        # Prefer aiohttp (discord.py dependency). Fallback to urllib in a thread.
        try:
            import aiohttp  # type: ignore
            timeout = aiohttp.ClientTimeout(total=max(5, int(timeout_s)))
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        try:
                            raw = await resp.text()
                        except Exception:
                            raw = ""
                        # Ollama commonly returns: {"error":"model 'x' not found"}
                        if "not found" in (raw or "").lower() and "model" in (raw or "").lower():
                            AI_LAST_ERROR = "model_not_found"
                            AI_LAST_ERROR_DETAIL = AI_MODEL
                        return None
                    data = await resp.json(content_type=None)
            if isinstance(data, dict):
                err = data.get("error")
                if isinstance(err, str) and err.strip():
                    if "not found" in err.lower() and "model" in err.lower():
                        AI_LAST_ERROR = "model_not_found"
                        AI_LAST_ERROR_DETAIL = AI_MODEL
                    return None
                msg = data.get("message") or {}
                content = msg.get("content") if isinstance(msg, dict) else None
                if isinstance(content, str) and content.strip():
                    return content.strip()
            return None
        except Exception:
            pass

        def _urllib_call() -> str | None:
            try:
                import urllib.request
                import json as _json
                req = urllib.request.Request(
                    url,
                    data=_json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=max(5, int(timeout_s))) as resp:
                    raw = resp.read().decode("utf-8", errors="ignore")
                data = _json.loads(raw) if raw else {}
                if isinstance(data, dict):
                    err = data.get("error")
                    if isinstance(err, str) and err.strip():
                        if "not found" in err.lower() and "model" in err.lower():
                            AI_LAST_ERROR = "model_not_found"
                            AI_LAST_ERROR_DETAIL = AI_MODEL
                        return None
                    msg = data.get("message") or {}
                    content = msg.get("content") if isinstance(msg, dict) else None
                    if isinstance(content, str) and content.strip():
                        return content.strip()
                return None
            except Exception:
                return None

        try:
            return await asyncio.wait_for(asyncio.to_thread(_urllib_call), timeout=timeout_s)
        except Exception:
            return None

    out = await _attempt(ctx_blob, max_tokens, timeout_s=25)
    if out:
        return out

    smaller_ctx = ctx_blob[:2500] if ctx_blob else ''
    smaller_tokens = max(200, min(int(max_tokens), 400))
    return await _attempt(smaller_ctx, smaller_tokens, timeout_s=18)


def _filter_messages_by_days(msgs: list[dict], days: int) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out: list[dict] = []
    for m in msgs:
        ts = m.get('timestamp') or m.get('time')
        if not ts:
            continue
        try:
            if isinstance(ts, (int, float)):
                dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            else:
                s = str(ts).strip()
                # Handle common ISO formats: '...Z' or with offset
                if s.endswith('Z'):
                    s = s[:-1] + '+00:00'
                dt = datetime.fromisoformat(s)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                dt = dt.astimezone(timezone.utc)
            if dt >= cutoff:
                out.append(m)
        except Exception:
            continue
    return out

def _compact_messages_for_ai(msgs: list[dict], limit_chars: int = 12000) -> str:
    # Keep the MOST RECENT messages within the limit, preserving chronological order.
    lines: list[str] = []
    total = 0
    for m in reversed(msgs):
        who = m.get('author') or m.get('user') or 'unknown'
        ts = m.get('timestamp') or m.get('time') or ''
        content = (m.get('content') or '').strip()
        if not content:
            continue
        line = f"[{ts}] {who}: {content}"
        if total + len(line) + 1 > limit_chars:
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(reversed(lines))


def _eboard_only():
    return commands.check(lambda ctx: isinstance(ctx.author, discord.Member) and is_eboard(ctx.author))

# ============================================================
# AI FEATURES (MANUAL COMMANDS ONLY)
# ============================================================

@bot.group(name="eboard", invoke_without_command=True)
@_eboard_only()
async def eboard_group(ctx: commands.Context):
    await ctx.send("Use `!eboard summarize [days]`, `!eboard decide <question>`")

@eboard_group.command(name="summarize")
@_eboard_only()
async def eboard_summarize_cmd(ctx: commands.Context, days: int = 7):
    """Summarize eboard-talk from the last N days (default 7)."""
    msgs = _filter_messages_by_days(_load_eboard_archive_messages(), max(1, min(days, 60)))
    if not msgs:
        await ctx.send("No archived eboard messages found for that window.")
        return

    blob = _compact_messages_for_ai(msgs)
    system = (
        "You are PowerBot. Summarize an e-board Discord planning discussion. "
        "Output: 1) Decisions, 2) Action items with owner if obvious, 3) Open questions. "
        "Be concise, bullet points ok, no long essays."
    )
    async with ctx.typing():
        reply = await ai_generate_text("Summarize this e-board discussion.", system=system, context=blob, max_tokens=650)
    if not reply:
        await ctx.send(_ai_unavailable_user_text())
        return
    await ctx.send(reply[:1900])

@eboard_group.command(name="decide")
@_eboard_only()
async def eboard_decide_cmd(ctx: commands.Context, *, question: str):
    """Ask 'when did we decide X' / decision lookup across archive."""
    msgs = _load_eboard_archive_messages()
    if not msgs:
        await ctx.send("No eboard archive loaded yet.")
        return

    # quick keyword prefilter to keep context small
    q = (question or "").lower()
    keys = [k for k in re.findall(r"[a-z0-9']+", q) if len(k) >= 4]
    pre = []
    if keys:
        for m in msgs:
            c=(m.get("content") or "").lower()
            if any(k in c for k in keys):
                pre.append(m)
    else:
        pre = msgs[-200:]
    pre = pre[-250:]
    blob = _compact_messages_for_ai(pre, limit_chars=14000)

    system = (
        "You are PowerBot. The user asks about a decision made in e-board chat. "
        "Answer with: (a) best guess decision, (b) timestamp(s) and who said it, "
        "and (c) quote small snippets (short) to justify. If not found, say not found."
    )
    async with ctx.typing():
        reply = await ai_generate_text(question, system=system, context=blob, max_tokens=700)
    if not reply:
        await ctx.send(_ai_unavailable_user_text())
        return
    await ctx.send(reply[:1900])

@bot.command(name="forecast_explain")
@_eboard_only()
async def forecast_explain_cmd(ctx: commands.Context, days: int = 120):
    """AI explanation of attendance trends using event history."""
    events = load_events()
    if not events:
        await ctx.send("No events logged yet.")
        return
    # summarize recent events for context
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(30, min(days, 3650)))
    rows=[]
    for e in events:
        ts=e.get("timestamp")
        try:
            dt=datetime.fromisoformat(ts).replace(tzinfo=None)
        except Exception:
            continue
        if dt >= cutoff:
            rows.append(f"{ts} | {e.get('event_type','?')} | {e.get('attendance','?')}")
    rows = rows[-80:]
    ctx_blob = (
        f"Config: total_members={config.get('total_members')} base_attendance={config.get('base_attendance')}\n"
        "Recent events (timestamp | type | attendance):\n" + "\n".join(rows)
    )
    system = (
        "You are PowerBot. Explain attendance patterns and suggest 2-3 actionable improvements. "
        "Be grounded in the event history. Avoid overconfident claims."
    )
    reply = await ai_generate_text("Explain our attendance trends and give recommendations.", system=system, context=ctx_blob, max_tokens=650)
    if not reply:
        await ctx.send(_ai_unavailable_user_text())
        return
    await ctx.send(reply[:1900])

@bot.command(name="promo_caption")
@_eboard_only()
async def promo_caption_cmd(ctx: commands.Context, *, event_desc: str):
    """Generate 3 caption options for Instagram/Discord."""
    club = KNOWLEDGE.get("club", {})
    tone = KNOWLEDGE.get("tone", {})
    style = "Energetic, friendly, club vibe, minimal emojis."
    ctx_blob = f"Club: {club.get('club_name','Your Club')} at {club.get('university','campus')}\nStyle: {style}\nTone snippets: {list(tone.keys())}"
    system = (
        "You are PowerBot. Write social captions for a university club. "
        "Return 3 options: 1 short, 1 medium, 1 hype. Include date/time placeholders if not provided. "
        "Keep it human and not cringe. Max 2 emojis per option."
    )
    reply = await ai_generate_text(event_desc, system=system, context=ctx_blob, max_tokens=500)
    if not reply:
        await ctx.send(_ai_unavailable_user_text())
        return
    await ctx.send(reply[:1900])

@bot.command(name="policy")
@_eboard_only()
async def policy_cmd(ctx: commands.Context, *, question: str):
    """Answer policy/procedure questions using campus + club memory."""
    campus = KNOWLEDGE.get("campus", {})
    club = KNOWLEDGE.get("club", {})
    # keep context compact
    ctx_blob = "Campus memory keys: " + ", ".join(list(campus.keys())[:60]) + "\n" + "Club memory keys: " + ", ".join(list(club.keys())[:60])
    system = (
        "You are PowerBot. Answer policy/procedure questions for a student club. "
        "Be cautious; if unsure, say what to verify. Keep concise."
    )
    reply = await ai_generate_text(question, system=system, context=ctx_blob, max_tokens=650)
    if not reply:
        await ctx.send(_ai_unavailable_user_text())
        return
    await ctx.send(reply[:1900])




# ==================================================
# OWNER-ONLY: PRIVATE CONSULT MODE
# ==================================================
# Notes:
# - Private Consult Mode is a "DM-like" AI conversation inside the server channel.
# - Only the configured owner can enable/use it.
# - When enabled, it automatically turns AI ON; disabling turns AI OFF.
# - Conversation is logged to: data/knowledge/ai_private_consultation.json

# OWNER_ID is defined at the top of the file

_PRIVATE_CONSULT_ACTIVE_KEY = "private_consult_active"
_PRIVATE_CONSULT_SESSION_KEY = "private_consult_session"
_PRIVATE_CONSULT_OWNER_KEY = "private_consult_owner_id"
_PRIVATE_CONSULT_LOG_PATH = "data/knowledge/ai_private_consultation.json"

def _is_owner(user: discord.abc.User | None) -> bool:
    """True if user is the configured bot owner (ID or optional role)."""
    if not user:
        return False
    try:
        if int(getattr(user, "id", 0) or 0) == int(OWNER_ID) and int(OWNER_ID) != 0:
            return True
    except Exception:
        pass
    # Optional role-based owner control (guild-only)
    if int(OWNER_ROLE_ID or 0) != 0:
        try:
            roles = getattr(user, "roles", []) or []
            for r in roles:
                if int(getattr(r, "id", 0) or 0) == int(OWNER_ROLE_ID):
                    return True
        except Exception:
            pass
    return False

def _owner_denied_text() -> str:
    # Keep it short and non-revealing.
    return "⛔ This command is limited to the configured **bot owner**."

def _load_private_consult_log() -> dict:
    data = _read_json_file(_PRIVATE_CONSULT_LOG_PATH, {})
    if not isinstance(data, dict) or "sessions" not in data:
        os.makedirs(os.path.dirname(_PRIVATE_CONSULT_LOG_PATH), exist_ok=True)
        data = {"sessions": []}
        _write_json_file(_PRIVATE_CONSULT_LOG_PATH, data)
    return data

def _save_private_consult_log(data: dict) -> None:
    os.makedirs(os.path.dirname(_PRIVATE_CONSULT_LOG_PATH), exist_ok=True)
    _write_json_file(_PRIVATE_CONSULT_LOG_PATH, data)

def _start_private_consult_session(user: discord.User) -> str:
    mem = _load_private_consult_log()
    sid = datetime.now(timezone.utc).isoformat()
    mem["sessions"].append({
        "session_id": sid,
        "user_id": str(user.id),
        "started_at": sid,
        "ended_at": None,
        "messages": [],
    })
    _save_private_consult_log(mem)
    return sid

def _close_private_consult_session(session_id: str) -> None:
    mem = _load_private_consult_log()
    for s in mem.get("sessions", []):
        if s.get("session_id") == session_id and not s.get("ended_at"):
            s["ended_at"] = datetime.now(timezone.utc).isoformat()
            break
    _save_private_consult_log(mem)

def _log_private_consult_msg(session_id: str, role: str, content: str) -> None:
    mem = _load_private_consult_log()
    for s in mem.get("sessions", []):
        if s.get("session_id") == session_id:
            s.setdefault("messages", []).append({
                "role": role,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "content": content,
            })
            break
    _save_private_consult_log(mem)

def _private_consult_is_active() -> bool:
    cfg = _read_json_file(CONFIG_PATH, {})
    return bool(cfg.get(_PRIVATE_CONSULT_ACTIVE_KEY, False))

def _private_consult_session_id() -> Optional[str]:
    cfg = _read_json_file(CONFIG_PATH, {})
    sid = cfg.get(_PRIVATE_CONSULT_SESSION_KEY)
    return str(sid) if sid else None

def _set_private_consult_state(active: bool, session_id: Optional[str]) -> None:
    cfg = _read_json_file(CONFIG_PATH, {})
    cfg[_PRIVATE_CONSULT_ACTIVE_KEY] = bool(active)
    cfg[_PRIVATE_CONSULT_SESSION_KEY] = session_id
    cfg[_PRIVATE_CONSULT_OWNER_KEY] = str(OWNER_ID)
    _write_json_file(CONFIG_PATH, cfg)
    try:
        global _CONFIG_MTIME
        _CONFIG_MTIME = os.path.getmtime(CONFIG_PATH)
    except Exception:
        pass

def _build_private_consult_context_blob() -> str:
    """Max knowledge blob (kept to a sane size)."""
    parts: list[str] = []
    # Club snapshot
    try:
        parts.append(_club_context_snippet())
    except Exception:
        pass

    # Knowledge JSON (club/campus/qa/tone)
    try:
        k = load_knowledge_json()
        # Keep this readable and version-control friendly
        parts.append("Knowledge JSON (club/campus/rules/tone):\n" + json.dumps(k, ensure_ascii=False, indent=2)[:12000])
    except Exception:
        pass

    # Recent e-board archive (last ~40 msgs)
    try:
        msgs = _load_eboard_archive_messages()
        tail = msgs[-40:] if isinstance(msgs, list) else []
        if tail:
            parts.append("Recent e-board discussion (most recent last):")
            for m in tail:
                author = (m.get("author") or m.get("user") or "unknown")
                content = (m.get("content") or "").strip()
                if not content:
                    continue
                ts = m.get("timestamp") or m.get("time") or ""
                parts.append(f"- [{ts}] {author}: {content}")
    except Exception:
        pass

    blob = "\n".join(p for p in parts if p).strip()
    # Hard cap to avoid runaway context
    return blob[:16000]


@bot.command(name="consult")
async def consult_toggle_cmd(ctx: commands.Context):
    """Owner-only: toggle private consult mode (auto AI on/off)."""
    if not _is_owner(getattr(ctx, "author", None)):
        await ctx.send(_owner_denied_text())
        return

    if _private_consult_is_active():
        sid = _private_consult_session_id()
        if sid:
            _close_private_consult_session(sid)
        _set_private_consult_state(False, None)
        _set_ai_enabled(False)
        await ctx.send("🛑 **Private Consult Mode disabled.** (AI OFF)")
        return

    # Enable
    _set_ai_enabled(True)
    sid = _start_private_consult_session(ctx.author)
    _set_private_consult_state(True, sid)
    await ctx.send(
        "⚠️ **Private Consult Mode ENABLED (Owner)**\n"
        "• Only the configured bot owner triggers responses\n"
        "• Advisory only (not decisions)\n"
        "• Logged to a private JSON file\n"
        "• Run `!consult` again to disable (also turns AI OFF)"
    )


_PRIVATE_CTX_CACHE = {'ts': 0.0, 'blob': ''}  # short-lived cache for consult context

async def _send_discord_long(channel: discord.abc.Messageable, text: str, *, limit: int = 2000):
    """Send a long message in <=limit chunks (Discord hard limit is 2000)."""
    if text is None:
        return
    text = str(text)
    # Normalize newlines
    text = text.replace("\r\n", "\n")
    if len(text) <= limit:
        await channel.send(text)
        return

    # Prefer splitting on line breaks, then spaces, then hard split.
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            await channel.send(remaining)
            break

        cut = remaining.rfind("\n", 0, limit + 1)
        if cut < 0:
            cut = remaining.rfind(" ", 0, limit + 1)
        if cut < 0 or cut < int(limit * 0.4):
            cut = limit

        chunk = remaining[:cut].rstrip()
        if chunk:
            await channel.send(chunk)
        remaining = remaining[cut:].lstrip()


# ---- Private consult helpers (smarter + faster) ----

_MONTHS = {
    'jan': 1, 'january': 1,
    'feb': 2, 'february': 2,
    'mar': 3, 'march': 3,
    'apr': 4, 'april': 4,
    'may': 5,
    'jun': 6, 'june': 6,
    'jul': 7, 'july': 7,
    'aug': 8, 'august': 8,
    'sep': 9, 'sept': 9, 'september': 9,
    'oct': 10, 'october': 10,
    'nov': 11, 'november': 11,
    'dec': 12, 'december': 12,
}


def _extract_days_from_text(text: str, default: int = 30, *, max_days: int = 180) -> int:
    t = (text or '').lower()
    m = re.search(r'\b(\d{1,3})\s*(?:day|days)\b', t)
    if not m:
        m = re.search(r'\bnext\s+(\d{1,3})\b', t)
    if not m:
        return default
    try:
        n = int(m.group(1))
        if n <= 0:
            return default
        return min(n, max_days)
    except Exception:
        return default


def _looks_like_timeline_query(text: str) -> bool:
    t = (text or '').lower()
    # Examples: "next 30 days", "what's planned", "upcoming", "this month"
    triggers = [
        'next 30', 'next thirty', 'next month', 'this month',
        'upcoming', 'what\'s planned', 'whats planned', 'planned in the next',
        'what\'s coming up', 'whats coming up', 'schedule for',
    ]
    return any(x in t for x in triggers) or bool(re.search(r'\bnext\s+\d{1,3}\s*days\b', t))


def _looks_like_tasks_query(text: str) -> bool:
    t = (text or '').lower()
    return any(x in t for x in [
        'what should i do', 'what do i do', 'what\'s planned for me', 'whats planned for me',
        'my tasks', 'my todo', 'my to-do', 'what am i supposed to do',
    ])


def _extract_named_lines(content: str, name: str, *, max_lines: int = 12) -> list[str]:
    if not content:
        return []
    out: list[str] = []
    needle = (name or '').strip().lower()
    for raw in content.splitlines():
        line = raw.strip()
        if not line:
            continue
        # ignore headings that are just the person's name
        if line.lower() == needle:
            continue
        if needle in line.lower():
            out.append(line)
            if len(out) >= max_lines:
                break
    return out


def _extract_dated_items_from_text(content: str, *, default_year: int) -> list[dict]:
    """Parse simple dated lines from planning notes.

    Supports:
    - "Feb 2 - Title" / "Feb. 2: Title" / "- Feb 16: Title"
    - "Jan. 23, 2026: Title"
    - "1/26" inside a line (uses default_year)
    """
    if not content:
        return []
    items: list[dict] = []

    # Month Day -/ : Title
    rx_md = re.compile(
        r"^\s*[-*•]?\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+(\d{1,2})\s*(?:-|:|–)\s*(.*)$",
        re.IGNORECASE,
    )

    # Month Day, Year: Title
    rx_mdy = re.compile(
        r"^\s*[-*•]?\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+(\d{1,2})\s*,\s*(\d{4})\s*(?:-|:|–)\s*(.*)$",
        re.IGNORECASE,
    )

    # mm/dd anywhere
    rx_slash = re.compile(r"\b(\d{1,2})/(\d{1,2})\b")

    for raw in content.splitlines():
        line = raw.strip()
        if not line:
            continue

        m = rx_mdy.match(line)
        if m:
            mon = _MONTHS.get(m.group(1).lower().rstrip('.'), None)
            if mon:
                try:
                    day = int(m.group(2))
                    yr = int(m.group(3))
                except Exception:
                    continue
                title = (m.group(4) or '').strip() or 'TBD'
                try:
                    d = date(yr, mon, day)
                except Exception:
                    continue
                items.append({'date': d, 'title': title, 'source': 'planning_notes'})
            continue

        m = rx_md.match(line)
        if m:
            mon = _MONTHS.get(m.group(1).lower().rstrip('.'), None)
            if not mon:
                continue
            try:
                day = int(m.group(2))
            except Exception:
                continue
            title = (m.group(3) or '').strip() or 'TBD'
            try:
                d = date(default_year, mon, day)
            except Exception:
                continue
            items.append({'date': d, 'title': title, 'source': 'planning_notes'})
            continue

        # mm/dd matches (could be multiple in a line)
        for mm, dd in rx_slash.findall(line):
            try:
                mon = int(mm)
                day = int(dd)
                d = date(default_year, mon, day)
            except Exception:
                continue
            # Keep a compact title (strip parentheses)
            title = re.sub(r"\(.*?\)", "", line).strip()
            if len(title) > 90:
                title = title[:90].rstrip() + '…'
            items.append({'date': d, 'title': title or 'TBD', 'source': 'planning_notes'})

    return items

def _build_timeline(days: int = 30) -> str:
    """Fast, non-AI timeline built from events.json + planning_notes.json."""
    today = datetime.now(timezone.utc).astimezone().date()
    end = today + timedelta(days=days)

    items: list[dict] = []

    # 1) Events (logged)
    try:
        for e in load_events():
            ts = e.get('timestamp') or e.get('date') or ''
            try:
                d = datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone(timezone.utc).date()
            except Exception:
                # allow YYYY-MM-DD
                try:
                    d = datetime.fromisoformat(ts).date()
                except Exception:
                    continue
            if today <= d <= end:
                et = (e.get('event_type') or 'event').strip()
                name = (e.get('name') or e.get('title') or '').strip()
                label = name if name else et
                items.append({'date': d, 'title': label, 'source': 'events'})
    except Exception:
        pass

    # 2) Planning notes entries
    planning = KNOWLEDGE.get('planning_notes', {}) if isinstance(KNOWLEDGE, dict) else {}
    entries = planning.get('entries', []) if isinstance(planning, dict) else []
    default_year = today.year
    for ent in entries:
        if not isinstance(ent, dict):
            continue
        # include the note itself if it is within range
        try:
            d = datetime.fromisoformat(str(ent.get('date',''))).date()
        except Exception:
            d = None
        if d and today <= d <= end:
            title = (ent.get('title') or ent.get('id') or 'planning note').strip()
            items.append({'date': d, 'title': f"Note: {title}", 'source': 'planning_notes'})

        # also parse dated GBM lines embedded in the note
        content = str(ent.get('content') or '')
        for it in _extract_dated_items_from_text(content, default_year=default_year):
            if today <= it['date'] <= end:
                items.append(it)

    items.sort(key=lambda x: x['date'])

    if not items:
        return (
            f"📅 **Next {days} days**\n"
            "No upcoming items found in `events.json` or dated planning notes yet.\n\n"
            "Tip: log events with `!events log ...` or add dated lines like `Feb. 2 - Icebreaker` to planning notes."
        )

    # De-dupe near-identical lines
    seen = set()
    clean = []
    for it in items:
        key = (it['date'].isoformat(), it['title'].lower())
        if key in seen:
            continue
        seen.add(key)
        clean.append(it)

    # Limit output
    max_items = 18
    shown = clean[:max_items]
    more = len(clean) - len(shown)

    lines = [f"📅 **Next {days} days** ({today.isoformat()} → {end.isoformat()})"]
    for it in shown:
        lines.append(f"- **{it['date'].strftime('%b %d')}** — {it['title']}")

    if more > 0:
        lines.append(f"…and **{more}** more items.")

    lines.append("\nIf you want, ask: `what should I do next?` and I’ll pull owner-specific action items.")
    return "\n".join(lines)


def _build_tasks_for_person(person: str = 'Owner', days: int = 45) -> str:
    """Extract action-ish lines mentioning a person from planning notes."""
    today = datetime.now(timezone.utc).astimezone().date()
    end = today + timedelta(days=days)

    planning = KNOWLEDGE.get('planning_notes', {}) if isinstance(KNOWLEDGE, dict) else {}
    entries = planning.get('entries', []) if isinstance(planning, dict) else []

    picked: list[tuple[date, str, str]] = []

    for ent in entries:
        if not isinstance(ent, dict):
            continue
        people = ent.get('people') or []
        if isinstance(people, list) and person not in people and person.title() not in people:
            # skip notes not involving this person
            continue

        # date filter (note date, not necessarily the task date)
        try:
            d = datetime.fromisoformat(str(ent.get('date',''))).date()
        except Exception:
            d = None
        if d and not (today - timedelta(days=365) <= d <= end):
            # allow older notes if still relevant, but cap very old
            continue

        title = (ent.get('title') or ent.get('id') or '').strip()
        lines = _extract_named_lines(str(ent.get('content') or ''), person, max_lines=12)
        for ln in lines:
            picked.append((d or today, title, ln))

    if not picked:
        return (
            f"✅ I don’t see any explicit **{person}** action items in planning notes yet.\n"
            "If you want, paste a task list here or add lines like `President: ...` to planning notes."
        )

    picked.sort(key=lambda x: x[0])

    # Keep it tight
    picked = picked[:14]

    out = [f"🧩 **{person} — likely action items** (next ~{days} days)"]
    for d, title, ln in picked:
        tag = f"({d.strftime('%b %d')})" if d else ''
        out.append(f"- {ln}  — _{title}_ {tag}".rstrip())

    out.append("\nIf any of these are outdated, tell me which one and I’ll adjust.")
    return "\n".join(out)


def _build_club_snippet_for_ai() -> str:
    """Compact but useful club snapshot for AI/consult."""
    mem = CLUB_MEMORY if isinstance(CLUB_MEMORY, dict) else {}
    meeting = mem.get("meeting", {}) or {}
    day = str(meeting.get("day", "Monday") or "Monday")
    time_ = str(meeting.get("time", MEETING_TIME) or MEETING_TIME)
    room = str(meeting.get("room", MEETING_ROOM) or MEETING_ROOM)

    eboard = mem.get("eboard", [])
    eboard_line = ""
    if isinstance(eboard, list) and eboard:
        pairs = []
        for r in eboard:
            if not isinstance(r, dict):
                continue
            role = str(r.get("role") or "").strip()
            name = str(r.get("name") or "").strip()
            if role and name:
                pairs.append(f"{role}: {name}")
        if pairs:
            eboard_line = "\nE-board: " + " | ".join(pairs[:10])

    return (
        f"Club: {mem.get('club_name','Your Club')} @ {mem.get('university','Your University')}.\n"
        f"Weekly meeting: {day}s {time_} in {room}." + eboard_line
    )


def _consult_schedule_snippet(user_text: str, *, max_people: int = 3, max_blocks_per_person: int = 6) -> str:
    """Return a small schedule snippet if the question seems schedule/availability related."""
    t = (user_text or "").lower()
    sched = KNOWLEDGE.get("schedules", {}) if isinstance(KNOWLEDGE, dict) else {}
    people = sched.get("people", {}) if isinstance(sched, dict) else {}
    if not isinstance(people, dict) or not people:
        return ""

    wants = any(k in t for k in ["schedule", "availability", "available", "free", "when can", "can we meet", "time works", "meeting"])
    mentions_known_person = any(str(name).lower() in t for name in people.keys())
    if not wants and not mentions_known_person:
        return ""

    # pick people mentioned; include the first matching person for context
    wanted = []
    for name in people.keys():
        if str(name).lower() in t:
            wanted.append(name)
    if not wanted and people:
        wanted.insert(0, next(iter(people.keys())))

    wanted = wanted[:max_people]

    out_lines = ["Schedules (busy blocks):"]
    for name in wanted:
        info = people.get(name, {})
        blocks = info.get("busy_blocks", []) if isinstance(info, dict) else []
        if not isinstance(blocks, list) or not blocks:
            continue
        out_lines.append(f"- {name}:")
        for b in blocks[:max_blocks_per_person]:
            if not isinstance(b, dict):
                continue
            day = b.get("day")
            start = b.get("start")
            end = b.get("end")
            kind = b.get("kind")
            title = b.get("title")
            out_lines.append(f"  • {day} {start}–{end} ({kind}) {title}")

    return "\n".join(out_lines)


def _consult_upcoming_snippet(days: int = 30, *, max_chars: int = 1400) -> str:
    try:
        s = _build_timeline(days).strip()
        if len(s) > max_chars:
            s = s[:max_chars].rstrip() + "…"
        return "Upcoming (fast timeline):\n" + s
    except Exception:
        return ""


def _consult_campus_snippet(user_text: str, *, max_chars: int = 1200) -> str:
    t = (user_text or "").lower()
    triggers = ["flyer", "approval", "posting", "room", "reservation", "cancellation", "no-show", "fee", "waiver", "finance", "purchase", "reimbursement"]
    if not any(x in t for x in triggers):
        return ""
    campus = KNOWLEDGE.get("campus", {}) if isinstance(KNOWLEDGE, dict) else {}
    if not isinstance(campus, dict) or not campus:
        return ""
    blob = json.dumps(campus, ensure_ascii=False, indent=2)
    if len(blob) > max_chars:
        blob = blob[:max_chars].rstrip() + "…"
    return "Campus / compliance memory (snippet):\n" + blob


def _build_consult_context(user_text: str, *, session_id: str | None = None) -> str:
    """Build a focused context block for consult.

    Goal: give the AI *relevant* slices of all JSON knowledge (club/campus/schedules/notes/rules)
    without dumping everything and hitting token limits.
    """
    parts: list[str] = []

    parts.append(_build_club_snippet_for_ai())

    # schedule
    sched = _consult_schedule_snippet(user_text)
    if sched:
        parts.append(sched)

    # short upcoming timeline
    up = _consult_upcoming_snippet(30)
    if up:
        parts.append(up)

    # relevant planning notes by keyword overlap
    q = (user_text or "").lower()
    tokens = set(re.findall(r"[a-zA-Z]{3,}", q))

    planning = KNOWLEDGE.get("planning_notes", {}) if isinstance(KNOWLEDGE, dict) else {}
    entries = planning.get("entries", []) if isinstance(planning, dict) else []

    scored: list[tuple[int, dict]] = []
    for ent in entries:
        if not isinstance(ent, dict):
            continue
        hay = (str(ent.get("title") or "") + "\n" + str(ent.get("content") or "")).lower()
        score = sum(1 for t in tokens if t in hay)
        if score > 0:
            scored.append((score, ent))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = [e for _, e in scored[:3]]

    if top:
        lines = ["Relevant planning notes (snippets):"]
        for ent in top:
            title = str(ent.get("title") or ent.get("id") or "note")
            date_str = str(ent.get("date") or "")
            content = str(ent.get("content") or "").strip()
            snippet = content.replace("\r\n", "\n")
            if len(snippet) > 900:
                snippet = snippet[:900].rstrip() + "…"
            lines.append(f"- {title} ({date_str}): {snippet}")
        parts.append("\n".join(lines))

    # Campus snippet when relevant
    campus_snip = _consult_campus_snippet(user_text)
    if campus_snip:
        parts.append(campus_snip)

    # consult history (last few turns)
    if session_id:
        try:
            log = _load_private_consult_log()
            sess = None
            for s in (log.get("sessions") or []):
                if s.get("session_id") == session_id:
                    sess = s
                    break
            if sess:
                msgs = sess.get("messages") or []
                tail = msgs[-6:]
                hist_lines = ["Recent consult chat:"]
                for m in tail:
                    role = m.get("role")
                    content = str(m.get("content") or "").strip()
                    if not content:
                        continue
                    if len(content) > 240:
                        content = content[:240].rstrip() + "…"
                    hist_lines.append(f"- {role}: {content}")
                if len(hist_lines) > 1:
                    parts.append("\n".join(hist_lines))
        except Exception:
            pass

    # Semantic hints from Q&A rules (optional)
    try:
        hits = query_index(question=user_text, index_dir=SEMANTIC_INDEX_DIR, k=3, min_score=0.33)
        if hits:
            hint_lines = ["Possible relevant Q&A rules (semantic):"]
            for h in hits[:3]:
                ans = h.meta.get("answer") or h.meta.get("response") or ""
                trig = h.meta.get("triggers") or []
                title = " | ".join([str(t) for t in trig][:3]) if isinstance(trig, list) else ""
                if not title:
                    title = str(h.meta.get("rule_id") or "rule")
                snippet = str(ans).strip().replace("\n", " ")
                if len(snippet) > 220:
                    snippet = snippet[:220].rstrip() + "…"
                hint_lines.append(f"- {title}: {snippet}")
            parts.append("\n".join(hint_lines))
    except Exception:
        pass

    ctx = "\n\n".join(p for p in parts if p)
    if len(ctx) > 9000:
        ctx = ctx[:9000].rstrip() + "\n…(context trimmed)"
    return ctx



async def maybe_handle_private_consult(message: discord.Message) -> bool:
    """Owner-only consult mode. Returns True if handled."""
    if message.author.bot:
        return False
    if not _is_owner(getattr(message, "author", None)):
        return False

    content = (message.content or '').strip()

    # Never hijack commands
    if content.startswith('!'):
        return False

    if not _private_consult_is_active():
        return False

    # If AI is unavailable, fail loudly but safely
    if not AI_ENABLED or not AI_AVAILABLE:
        await message.channel.send(
            _ai_unavailable_user_text()
        )
        return True

    # Recover missing session
    sid = _private_consult_session_id()
    if not sid:
        sid = _start_private_consult_session(message.author)
        _set_private_consult_state(True, sid)

    user_text = content

    # Log user message first
    _log_private_consult_msg(sid, 'user', user_text)

    # Fast paths (no AI): timelines + "what should I do" tasks
    try:
        if _looks_like_timeline_query(user_text):
            days = _extract_days_from_text(user_text, default=30)
            await _send_discord_long(message.channel, _build_timeline(days))
            return True

        if _looks_like_tasks_query(user_text):
            days = _extract_days_from_text(user_text, default=45)
            await _send_discord_long(message.channel, _build_tasks_for_person('Owner', days))
            return True

        # Confusion / clarification prompts
        if re.match(r"^(um|uh|huh|what)\b", user_text.lower()):
            await message.channel.send(
                "Do you want:\n"
                "1) a **next 30 days** timeline\n"
                "2) **Owner-specific tasks**\n"
                "3) an answer to a specific question?\n\n"
                "Say: `next 30 days` or `what should I do next` or ask the specific thing."
            )
            return True
    except Exception:
        # If fast-path parsing fails, just fall through to AI.
        pass

    system = (
        _build_ai_system_prompt()
        + "\n\nYou are in **Private Consult Mode** with the configured bot owner. "
          "Give practical, logical advice for running a student org. "
          "Do NOT create policy, do NOT claim authority. "
          "Do NOT assume the question is about earlier channel chat unless the user explicitly references it. "
          "If the request is vague, ask 1 short clarifying question before giving recommendations. "
          "Keep answers structured and concise."
    )

    ctx_blob = _build_consult_context(user_text, session_id=sid)

    try:
        async with message.channel.typing():
            reply = await ai_generate_text(user_text, system=system, context=ctx_blob, max_tokens=450)
    except Exception as e:
        print('[PowerBot] Private consult AI error:', repr(e))
        await message.channel.send('⚠️ Something went wrong while thinking. Check logs.')
        return True

    if not reply:
        # Graceful fallback: give a mini-dashboard rather than a dead-end
        fallback = (
            "⚠️ AI didn’t respond in time. Here are quick options:\n"
            "- Say `next 30 days` for a timeline\n"
            "- Say `what should I do next` for owner tasks\n"
            "- Or try again in a moment."
        )
        await message.channel.send(fallback)
        return True

    _log_private_consult_msg(sid, 'assistant', reply)
    await _send_discord_long(message.channel, reply)
    return True

# ---------------- ERROR VISIBILITY (NO SILENT FAILS) ---------------- #

def _new_error_id() -> str:
    return uuid.uuid4().hex[:8]

async def _try_dm_owner(content: str):
    """Best-effort: DM the owner (won't spam channels)."""
    try:
        owner = bot.get_user(OWNER_ID) or await bot.fetch_user(OWNER_ID)
        if owner:
            await owner.send(content)
    except Exception:
        return

@bot.event
async def on_command_error(ctx: commands.Context, error: Exception):
    # Ignore CommandNotFound to avoid spam
    if isinstance(error, commands.CommandNotFound):
        return

    err = getattr(error, 'original', error)

    if isinstance(err, commands.CheckFailure):
        # Differentiate owner-only commands vs eboard-only commands.
        root = ''
        try:
            if ctx.command:
                root = (ctx.command.qualified_name or ctx.command.name or '').split(' ')[0].lower()
        except Exception:
            root = ''

        owner_only_roots = {'consult', 'ai'}
        try:
            if root in owner_only_roots:
                await ctx.send(_owner_denied_text())
            else:
                await ctx.send('❌ This is **E-board only**.')
        except Exception:
            pass
        return

    eid = _new_error_id()
    print(f"[PowerBot ERROR {eid}] on_command_error:")
    traceback.print_exception(type(err), err, err.__traceback__)

    # Visible but not spammy message
    try:
        await ctx.send(f"⚠️ Something went wrong. Check logs for details. (Error ID: `{eid}`)")
    except Exception:
        pass

    await _try_dm_owner(f"PowerBot error `{eid}` in command `{getattr(ctx.command, 'qualified_name', 'unknown')}`: {type(err).__name__}\n\n{err}")

@bot.event
async def on_error(event_method: str, *args, **kwargs):
    eid = _new_error_id()
    print(f"[PowerBot ERROR {eid}] on_error in {event_method}:")
    traceback.print_exc()
    await _try_dm_owner(f"PowerBot error `{eid}` in event `{event_method}`. Check logs for traceback.")


# ---------------- RUN BOT ----------------------- #


def run() -> None:
    """Entrypoint for running the bot.

    Keeping this in a function allows bot.py to stay tiny.
    """
    def _print_first_run_setup() -> None:
        print(
            "PowerBot setup required:\n\n"
            "1. Copy .env.example → .env\n"
            "2. Add your Discord bot token\n"
            "3. Run start.bat again\n"
        )

    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    env_missing = not os.path.exists(env_path)
    token = (os.getenv("DISCORD_TOKEN") or "").strip()
    if env_missing or not token:
        _print_first_run_setup()
        return

    # Friendly onboarding hint: owner controls are optional but recommended.
    try:
        cfg = load_config()
        needs_owner = (str(cfg.get("private_consult_owner_id") or "").strip() in {""}) and int(OWNER_ID or 0) == 0 and int(OWNER_ROLE_ID or 0) == 0
        if needs_owner:
            print(
                "\nPowerBot tip:\n"
                "- Set POWERBOT_OWNER_ID (and optionally POWERBOT_OWNER_ROLE_ID) in .env for owner-only controls.\n"
            )
    except Exception:
        pass
    # Pre-init (safe to call multiple times)
    perform_startup_backups()
    init_db()
    init_scheduler()
    bot.run(token)


if __name__ == "__main__":
    run()