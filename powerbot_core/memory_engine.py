from __future__ import annotations

from typing import Any

from .utils import clip, normalize_spaces, safe_read_json, text_score


class MemoryEngine:
    def __init__(self, planning_notes_path: str, archive_path: str, club_memory_path: str):
        self.planning_notes_path = planning_notes_path
        self.archive_path = archive_path
        self.club_memory_path = club_memory_path

    def lookup(self, query: str) -> str:
        q = normalize_spaces(query)
        low = q.lower()
        hits: list[tuple[int, str, str]] = []

        notes = safe_read_json(self.planning_notes_path, {})
        entries = notes.get("entries") if isinstance(notes, dict) else []
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                title = str(entry.get("title") or entry.get("id") or "note")
                content = str(entry.get("content") or "")
                hay = f"{title}\n{content}".lower()
                score = text_score(low, hay)
                if score <= 0:
                    continue
                snippet = clip(content.replace("\n", " ").strip(), 200)
                hits.append((score, "planning", f"- **Planning note:** {title} — {snippet}"))

        archive = safe_read_json(self.archive_path, {})
        messages = archive.get("messages") if isinstance(archive, dict) else []
        if isinstance(messages, list):
            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                content = str(msg.get("content") or "")
                hay = content.lower()
                score = text_score(low, hay)
                if score <= 0:
                    continue
                author = str(msg.get("author") or "unknown")
                ts = str(msg.get("timestamp") or "")[:10]
                snippet = clip(content.replace("\n", " ").strip(), 170)
                hits.append((score, "archive", f"- **Archive:** {ts} {author} — {snippet}"))

        club_memory = safe_read_json(self.club_memory_path, {})
        if isinstance(club_memory, dict):
            for key, value in club_memory.items():
                hay = str(value)
                score = text_score(low, f"{key} {hay}".lower())
                if score <= 0:
                    continue
                snippet = clip(str(value).replace("\n", " "), 180)
                hits.append((score, "club", f"- **Club memory:** {key} — {snippet}"))

        hits.sort(key=lambda x: x[0], reverse=True)
        if not hits:
            return "🧠 **Memory lookup**\n- I couldn't find a strong match yet. Try naming the event, person, or topic more specifically."

        lines = ["🧠 **Memory lookup**"]
        seen = set()
        for _, source, line in hits:
            if line in seen:
                continue
            seen.add(line)
            lines.append(line)
            if len(lines) >= 7:
                break
        source_counts: dict[str, int] = {}
        for _, source, _ in hits[:10]:
            source_counts[source] = source_counts.get(source, 0) + 1
        if source_counts:
            lines.append(f"\nSources hit: {', '.join(f'{k}={v}' for k, v in source_counts.items())}")
        return "\n".join(lines)
