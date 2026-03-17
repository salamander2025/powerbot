from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .utils import clip, normalize_spaces, safe_read_json


class MeetingEngine:
    def __init__(self, archive_path: str, eboard_log_path: str):
        self.archive_path = archive_path
        self.eboard_log_path = eboard_log_path

    def summarize_recent(self, limit: int = 120) -> str:
        archive = safe_read_json(self.archive_path, {})
        messages = archive.get("messages") if isinstance(archive, dict) else []
        recent = [m for m in messages if isinstance(m, dict)][-limit:]

        if not recent:
            try:
                raw = open(self.eboard_log_path, "r", encoding="utf-8").read().strip()
            except Exception:
                raw = ""
            if not raw:
                return "📝 **Meeting summary**\n- No recent E-board archive messages found."
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            recent_lines = lines[-10:]
            return "📝 **Meeting summary**\n" + "\n".join(f"- {clip(line, 180)}" for line in recent_lines)

        authors = Counter(str(m.get("author") or "unknown") for m in recent)
        top_authors = ", ".join(f"{name} ({count})" for name, count in authors.most_common(5))

        action_lines: list[str] = []
        decision_lines: list[str] = []
        unresolved_lines: list[str] = []
        action_keywords = ("email", "confirm", "post", "submit", "buy", "assign", "handle", "need", "should", "send", "update", "make sure")
        decision_keywords = ("we should", "let's", "lets", "decided", "going with", "approved", "confirmed", "plan is", "we're doing", "we are doing")
        unresolved_keywords = ("not sure", "need to figure out", "still need", "haven't", "havent", "pending", "idk", "don't know", "dont know")

        for msg in recent:
            content = normalize_spaces(str(msg.get("content") or ""))
            if not content or content.startswith("http"):
                continue
            low = content.lower()
            author = str(msg.get("author") or "unknown")
            action_title = self._extract_action_title(content)
            if action_title and any(k in low for k in action_keywords):
                owner = self._guess_owner(content, author)
                action_lines.append(f"- {owner} → {clip(action_title, 170)}")
            if any(k in low for k in decision_keywords):
                decision_lines.append(f"- {clip(content, 170)}")
            if any(k in low for k in unresolved_keywords):
                unresolved_lines.append(f"- {clip(content, 170)}")

        lines = ["📝 **Recent E-board summary**", f"**Most active in this slice:** {top_authors}"]
        if decision_lines:
            lines.append("\n**Likely decisions**")
            lines.extend(self._dedupe_lines(decision_lines)[:6])
        if action_lines:
            lines.append("\n**Likely action items**")
            lines.extend(self._dedupe_lines(action_lines)[:8])
        if unresolved_lines:
            lines.append("\n**Open / unresolved**")
            lines.extend(self._dedupe_lines(unresolved_lines)[:5])
        if not decision_lines and not action_lines and not unresolved_lines:
            lines.append("- I found recent chat, but no obvious action-heavy lines in the latest slice.")
        return "\n".join(lines)

    def extract_action_items(self, limit: int = 180) -> list[dict[str, str]]:
        archive = safe_read_json(self.archive_path, {})
        messages = archive.get("messages") if isinstance(archive, dict) else []
        recent = [m for m in messages if isinstance(m, dict)][-limit:]
        results: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for msg in recent:
            content = normalize_spaces(str(msg.get("content") or ""))
            if not content:
                continue
            action_title = self._extract_action_title(content)
            if not action_title:
                continue
            owner = self._guess_owner(content, str(msg.get("author") or "unknown"))
            key = (owner.lower(), re.sub(r"\s+", " ", action_title.lower()).strip())
            if key in seen:
                continue
            seen.add(key)
            results.append(
                {
                    "owner": owner,
                    "title": clip(action_title, 120),
                    "timestamp": str(msg.get("timestamp") or ""),
                }
            )
        return results[:15]

    def _extract_action_title(self, content: str) -> str | None:
        text = normalize_spaces(content)
        low = text.lower()
        banlist = (
            "don't send",
            "dont send",
            "didnt send",
            "didn't send",
            "email etiquette",
            "incorrect grammar",
            "not good at all",
            "omg",
            "i'm sorry",
            "im sorry",
            "stressing me out",
            "too casual",
            "0 email etiquette",
        )
        if any(b in low for b in banlist):
            return None
        if "?" in text and not any(x in low for x in ["can you", "could you", "should we"]):
            return None
        patterns = [
            r"(?:need to|still need to|have to|has to|must) (?P<action>.+)",
            r"(?:can you|could you|please) (?P<action>.+)",
        ]
        for pattern in patterns:
            m = re.search(pattern, low, flags=re.IGNORECASE)
            if not m:
                continue
            action = normalize_spaces(m.group("action"))
            if len(action.split()) < 2:
                continue
            action = re.sub(r"^[^a-zA-Z]+", "", action)
            action = action.rstrip(".!")
            if action:
                strong_prefixes = (
                    "email ", "confirm ", "post ", "submit ", "buy ", "assign ", "finalize ", "update ",
                    "reserve ", "contact ", "schedule ", "draft ", "approve ",
                )
                strong_phrases = (
                    "send email", "write reply", "create flyer", "make flyer", "submit form", "confirm room", "post flyer",
                )
                if any(action.startswith(prefix) for prefix in strong_prefixes) or any(phrase in action for phrase in strong_phrases):
                    return action
        return None

    def _dedupe_lines(self, lines: list[str]) -> list[str]:
        seen = set()
        out = []
        for line in lines:
            key = re.sub(r"\s+", " ", line.lower()).strip()
            if key in seen:
                continue
            seen.add(key)
            out.append(line)
        return out

    def _guess_owner(self, content: str, author: str) -> str:
        for name in ("President", "Vice President", "Treasurer", "Secretary", "Event Chair", "Marketing Lead"):
            if re.search(rf"\b{name.lower()}\b", content.lower()):
                return name
        return author
