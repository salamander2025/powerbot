"""SQLite storage for PowerBot.

We keep JSON for portability, but SQLite is better for structured logs.
This module provides a tiny wrapper with automatic schema creation.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PowerBotDB:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._conn = sqlite3.connect(self.db_path, timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._apply_pragmas()
        self._ensure_schema()

    def _apply_pragmas(self) -> None:
        try:
            cur = self._conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL;")
            cur.execute("PRAGMA synchronous=NORMAL;")
            cur.execute("PRAGMA temp_store=MEMORY;")
            cur.execute("PRAGMA foreign_keys=ON;")
            self._conn.commit()
        except Exception:
            return

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def _ensure_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                guild_id TEXT,
                channel_id TEXT,
                user_id TEXT,
                user_name TEXT,
                question TEXT,
                answer TEXT,
                used_rule INTEGER DEFAULT 0,
                used_semantic INTEGER DEFAULT 0,
                used_ai INTEGER DEFAULT 0
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                event_id INTEGER,
                event_type TEXT,
                attendance INTEGER,
                notes TEXT,
                logged_by TEXT
            );
            """
        )

        # Anti-spam / safety telemetry (non-punitive by default)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS spam_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                guild_id TEXT,
                channel_id TEXT,
                channel_name TEXT,
                user_id TEXT,
                user_name TEXT,
                score INTEGER,
                reasons TEXT,
                snippet TEXT,
                jump_url TEXT
            );
            """
        )

        # Budget / finance tracking
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT,
                note TEXT,
                event_id INTEGER,
                logged_by TEXT
            );
            """
        )

        # Member count history (for growth trends)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS member_counts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                total_members INTEGER NOT NULL,
                source TEXT,
                logged_by TEXT
            );
            """
        )

        
        # Activity tracking (daily aggregates; no message content stored)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS activity_daily (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL,
                guild_id TEXT,
                channel_id TEXT,
                user_id TEXT,
                user_name TEXT,
                messages INTEGER NOT NULL DEFAULT 0,
                chars INTEGER NOT NULL DEFAULT 0,
                links INTEGER NOT NULL DEFAULT 0,
                attachments INTEGER NOT NULL DEFAULT 0
            );
            """
        )
# Decision logging (what/why, tied to outcomes later)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                question TEXT NOT NULL,
                recommendation TEXT,
                rationale TEXT,
                logged_by TEXT
            );
            """
        )

        
        # Per-user conversational memory (lightweight profile)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                user_name TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                interactions INTEGER NOT NULL DEFAULT 0,
                last_channel_id TEXT,
                last_command TEXT,
                last_summary TEXT
            );
            """
        )

        cur.execute("CREATE INDEX IF NOT EXISTS idx_interactions_ts ON interactions(ts)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_attendance_event_type ON attendance(event_type, ts)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_expenses_event_id ON expenses(event_id, ts)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_spam_events_ts ON spam_events(ts)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_activity_daily_lookup ON activity_daily(day, guild_id, channel_id, user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_member_counts_ts ON member_counts(ts)")
        self._conn.commit()

    def log_interaction(
        self,
        *,
        guild_id: Optional[str],
        channel_id: Optional[str],
        user_id: Optional[str],
        user_name: Optional[str],
        question: str,
        answer: str,
        used_rule: bool = False,
        used_semantic: bool = False,
        used_ai: bool = False,
    ) -> None:
        try:
            self._conn.execute(
                """
                INSERT INTO interactions (ts, guild_id, channel_id, user_id, user_name, question, answer, used_rule, used_semantic, used_ai)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utcnow_iso(),
                    guild_id,
                    channel_id,
                    user_id,
                    user_name,
                    question,
                    answer,
                    1 if used_rule else 0,
                    1 if used_semantic else 0,
                    1 if used_ai else 0,
                ),
            )
            self._conn.commit()
        except Exception:
            return

    def log_attendance(
        self,
        *,
        event_id: Optional[int],
        event_type: str,
        attendance: int,
        notes: str,
        logged_by: str,
        ts: Optional[str] = None,
    ) -> None:
        try:
            self._conn.execute(
                """
                INSERT INTO attendance (ts, event_id, event_type, attendance, notes, logged_by)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (ts or utcnow_iso(), event_id, event_type, int(attendance), notes, logged_by),
            )
            self._conn.commit()
        except Exception:
            return

    def stats(self) -> Dict[str, Any]:
        cur = self._conn.cursor()
        out: Dict[str, Any] = {}
        try:
            out["interactions"] = int(cur.execute("SELECT COUNT(*) FROM interactions").fetchone()[0])
            out["attendance_rows"] = int(cur.execute("SELECT COUNT(*) FROM attendance").fetchone()[0])
            out["spam_events"] = int(cur.execute("SELECT COUNT(*) FROM spam_events").fetchone()[0])
            out["expense_rows"] = int(cur.execute("SELECT COUNT(*) FROM expenses").fetchone()[0])
            out["member_count_rows"] = int(cur.execute("SELECT COUNT(*) FROM member_counts").fetchone()[0])
        except Exception:
            out["interactions"] = 0
            out["attendance_rows"] = 0
            out["spam_events"] = 0
            out["expense_rows"] = 0
            out["member_count_rows"] = 0
        return out

    def log_spam_event(
        self,
        *,
        guild_id: Optional[str],
        channel_id: Optional[str],
        channel_name: Optional[str],
        user_id: Optional[str],
        user_name: Optional[str],
        score: int,
        reasons: str,
        snippet: str,
        jump_url: str,
    ) -> None:
        try:
            self._conn.execute(
                """
                INSERT INTO spam_events (ts, guild_id, channel_id, channel_name, user_id, user_name, score, reasons, snippet, jump_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utcnow_iso(),
                    guild_id,
                    channel_id,
                    channel_name,
                    user_id,
                    user_name,
                    int(score),
                    reasons,
                    snippet,
                    jump_url,
                ),
            )
            self._conn.commit()
        except Exception:
            return

    def recent_interactions(self, limit: int = 10) -> List[Dict[str, Any]]:
        cur = self._conn.cursor()
        rows = cur.execute(
            "SELECT ts, user_name, question, used_rule, used_semantic, used_ai FROM interactions ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]


    def log_expense(
        self,
        *,
        amount: float,
        category: str = "misc",
        note: str = "",
        event_id: Optional[int] = None,
        logged_by: str = "",
        ts: Optional[str] = None,
    ) -> None:
        try:
            self._conn.execute(
                """
                INSERT INTO expenses (ts, amount, category, note, event_id, logged_by)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (ts or utcnow_iso(), float(amount), category, note, event_id, logged_by),
            )
            self._conn.commit()
        except Exception:
            return

    def sum_expenses(self) -> float:
        try:
            cur = self._conn.cursor()
            val = cur.execute("SELECT COALESCE(SUM(amount), 0) FROM expenses").fetchone()[0]
            return float(val or 0)
        except Exception:
            return 0.0

    def recent_expenses(self, limit: int = 5) -> List[Dict[str, Any]]:
        try:
            cur = self._conn.cursor()
            rows = cur.execute(
                "SELECT ts, amount, category, note, event_id, logged_by FROM expenses ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def log_member_count(
        self,
        *,
        total_members: int,
        source: str = "manual",
        logged_by: str = "",
        ts: Optional[str] = None,
    ) -> None:
        try:
            self._conn.execute(
                """
                INSERT INTO member_counts (ts, total_members, source, logged_by)
                VALUES (?, ?, ?, ?)
                """,
                (ts or utcnow_iso(), int(total_members), source, logged_by),
            )
            self._conn.commit()
        except Exception:
            return

    def latest_member_count(self) -> Optional[int]:
        try:
            cur = self._conn.cursor()
            row = cur.execute(
                "SELECT total_members FROM member_counts ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return int(row[0]) if row else None
        except Exception:
            return None


    def update_user_memory(
        self,
        *,
        user_id: str,
        user_name: str = "",
        channel_id: Optional[str] = None,
        command_name: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> None:
        """Upsert a lightweight per-user memory row.

        This stays intentionally compact so the DB does not turn into a
        full transcript store, but still lets PowerBot adapt to people
        over time.
        """
        try:
            cur = self._conn.cursor()
            now = utcnow_iso()
            row = cur.execute(
                "SELECT id, interactions FROM user_memory WHERE user_id = ?",
                (user_id,),
            ).fetchone()

            interactions = 1
            if row:
                interactions = int(row[1] or 0) + 1
                cur.execute(
                    """
                    UPDATE user_memory
                    SET user_name = ?, last_seen = ?, interactions = ?,
                        last_channel_id = ?, last_command = ?, last_summary = ?
                    WHERE user_id = ?
                    """,
                    (
                        user_name or "",
                        now,
                        interactions,
                        channel_id,
                        command_name,
                        summary,
                        user_id,
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO user_memory (
                        user_id,
                        user_name,
                        first_seen,
                        last_seen,
                        interactions,
                        last_channel_id,
                        last_command,
                        last_summary
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        user_name or "",
                        now,
                        now,
                        interactions,
                        channel_id,
                        command_name,
                        summary,
                    ),
                )

            self._conn.commit()
        except Exception:
            return

    def get_user_memory(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Return the saved profile for a given user_id, if any."""
        try:
            cur = self._conn.cursor()
            row = cur.execute(
                """
                SELECT user_id,
                       user_name,
                       first_seen,
                       last_seen,
                       interactions,
                       last_channel_id,
                       last_command,
                       last_summary
                FROM user_memory
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
            if not row:
                return None
            keys = [
                "user_id",
                "user_name",
                "first_seen",
                "last_seen",
                "interactions",
                "last_channel_id",
                "last_command",
                "last_summary",
            ]
            return dict(zip(keys, row))
        except Exception:
            return None


    # ---------------- ACTIVITY (DAILY AGGREGATES) ---------------- #

    def incr_activity_daily(
        self,
        *,
        day: str,
        guild_id: str | None,
        channel_id: str | None,
        user_id: str | None,
        user_name: str | None,
        chars: int = 0,
        links: int = 0,
        attachments: int = 0,
    ) -> None:
        """Increment daily activity counters. Stores no message content."""
        try:
            cur = self._conn.cursor()
            row = cur.execute(
                """
                SELECT id, messages, chars, links, attachments
                FROM activity_daily
                WHERE day = ? AND guild_id = ? AND channel_id = ? AND user_id = ?
                """,
                (day, guild_id, channel_id, user_id),
            ).fetchone()

            if row:
                cur.execute(
                    """
                    UPDATE activity_daily
                    SET user_name = ?,
                        messages = ?,
                        chars = ?,
                        links = ?,
                        attachments = ?
                    WHERE id = ?
                    """,
                    (
                        user_name or "",
                        int(row["messages"] or 0) + 1,
                        int(row["chars"] or 0) + int(chars or 0),
                        int(row["links"] or 0) + int(links or 0),
                        int(row["attachments"] or 0) + int(attachments or 0),
                        int(row["id"]),
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO activity_daily (
                        day, guild_id, channel_id, user_id, user_name, messages, chars, links, attachments
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        day,
                        guild_id,
                        channel_id,
                        user_id,
                        user_name or "",
                        1,
                        int(chars or 0),
                        int(links or 0),
                        int(attachments or 0),
                    ),
                )

            self._conn.commit()
        except Exception:
            return

    def top_activity_users(self, *, guild_id: str | None, days: int = 7, limit: int = 10) -> list[dict]:
        """Return top users by message count over the last N days."""
        try:
            cur = self._conn.cursor()
            rows = cur.execute(
                """
                SELECT user_id,
                       MAX(user_name) AS user_name,
                       SUM(messages) AS messages,
                       SUM(chars) AS chars,
                       SUM(links) AS links,
                       SUM(attachments) AS attachments
                FROM activity_daily
                WHERE guild_id = ?
                  AND day >= date('now', ?)
                GROUP BY user_id
                ORDER BY SUM(messages) DESC
                LIMIT ?
                """,
                (guild_id, f"-{int(days)} day", int(limit)),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    

    def top_activity_channels(self, *, guild_id: str | None, days: int = 7, limit: int = 10) -> list[dict]:
        """Return top channels by message count over the last N days."""
        try:
            cur = self._conn.cursor()
            rows = cur.execute(
                """
                SELECT channel_id,
                       SUM(messages) AS messages,
                       SUM(chars) AS chars,
                       SUM(links) AS links,
                       SUM(attachments) AS attachments
                FROM activity_daily
                WHERE guild_id = ?
                  AND day >= date('now', ?)
                GROUP BY channel_id
                ORDER BY SUM(messages) DESC
                LIMIT ?
                """,
                (guild_id, f"-{int(days)} day", int(limit)),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def sum_expenses_for_event(self, event_id: int) -> float:
        try:
            cur = self._conn.cursor()
            val = cur.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE event_id = ?",
                (int(event_id),),
            ).fetchone()[0]
            return float(val or 0)
        except Exception:
            return 0.0

    # ---------------- DECISIONS ---------------- #

    def log_decision(self, *, question: str, recommendation: str = "", rationale: str = "", logged_by: str = "") -> None:
        try:
            self._conn.execute(
                """
                INSERT INTO decisions (ts, question, recommendation, rationale, logged_by)
                VALUES (?, ?, ?, ?, ?)
                """,
                (utcnow_iso(), question, recommendation, rationale, logged_by),
            )
            self._conn.commit()
        except Exception:
            return

    def recent_decisions(self, limit: int = 5) -> list[dict]:
        try:
            cur = self._conn.cursor()
            rows = cur.execute(
                """
                SELECT ts, question, recommendation, rationale, logged_by
                FROM decisions
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def search_decisions(self, query: str, limit: int = 10) -> list[dict]:
        try:
            q = f"%{(query or '').strip()}%"
            cur = self._conn.cursor()
            rows = cur.execute(
                """
                SELECT ts, question, recommendation, rationale, logged_by
                FROM decisions
                WHERE question LIKE ? OR recommendation LIKE ? OR rationale LIKE ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (q, q, q, int(limit)),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []
