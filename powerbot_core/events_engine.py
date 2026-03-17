from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from .utils import clip, normalize_spaces, relative_due_date, safe_read_json, safe_write_json, slugify, text_score, title_case_safe, try_parse_date


class EventsEngine:
    def __init__(self, events_path: str, planning_notes_path: str):
        self.events_path = events_path
        self.planning_notes_path = planning_notes_path

    def load_events(self) -> list[dict[str, Any]]:
        data = safe_read_json(self.events_path, [])
        raw_events: list[dict[str, Any]] = []
        if isinstance(data, list):
            raw_events = [e for e in data if isinstance(e, dict)]
        elif isinstance(data, dict) and isinstance(data.get("events"), list):
            raw_events = [e for e in data.get("events", []) if isinstance(e, dict)]
        events = [self._normalize_event(e) for e in raw_events]
        if any(int(e.get("id") or 0) <= 0 for e in events):
            next_id = 1
            for event in events:
                if int(event.get("id") or 0) <= 0:
                    event["id"] = next_id
                    next_id += 1
                else:
                    next_id = max(next_id, int(event["id"]) + 1)
            self.save_events(events)
        return events

    def save_events(self, events: list[dict[str, Any]]) -> None:
        safe_write_json(self.events_path, events)

    def _normalize_event(self, event: dict[str, Any]) -> dict[str, Any]:
        name = normalize_spaces(str(event.get("name") or event.get("title") or event.get("event_type") or "event"))
        d = self._parse_date(event.get("timestamp") or event.get("date"))
        return {
            "id": int(event.get("id") or 0),
            "slug": event.get("slug") or slugify(name),
            "name": name,
            "date": d.isoformat() if d else None,
            "event_type": normalize_spaces(str(event.get("event_type") or "")) or None,
            "attendance": self._normalize_int(event.get("attendance")),
            "expected_attendance": self._normalize_int(event.get("expected_attendance")),
            "budget": self._normalize_float(event.get("budget")),
            "location": normalize_spaces(str(event.get("location") or "")) or None,
            "status": normalize_spaces(str(event.get("status") or "logged")) or "logged",
            "notes": normalize_spaces(str(event.get("notes") or "")) or None,
            "logged_by": normalize_spaces(str(event.get("logged_by") or "")) or None,
        }

    def add_event(
        self,
        name: str,
        *,
        date_text: str | None = None,
        location: str | None = None,
        status: str | None = None,
        logged_by: str | None = None,
        event_type: str | None = None,
    ) -> dict[str, Any]:
        events = self.load_events()
        existing = self.find_event(name)
        if existing:
            return existing
        next_id = max((int(e.get("id") or 0) for e in events), default=0) + 1
        parsed_date = self._parse_date(date_text)
        event = {
            "id": next_id,
            "slug": slugify(name),
            "name": normalize_spaces(name),
            "date": parsed_date.isoformat() if parsed_date else None,
            "event_type": normalize_spaces(event_type or "") or None,
            "attendance": None,
            "expected_attendance": None,
            "budget": None,
            "location": normalize_spaces(location or "") or None,
            "status": normalize_spaces(status or "planned") or "planned",
            "notes": None,
            "logged_by": normalize_spaces(logged_by or "") or None,
        }
        events.append(event)
        self.save_events(events)
        return event

    def update_event(
        self,
        event_name: str,
        *,
        date_text: str | None = None,
        location: str | None = None,
        status: str | None = None,
        attendance: int | None = None,
        budget: float | None = None,
        notes: str | None = None,
    ) -> dict[str, Any] | None:
        events = self.load_events()
        found = None
        for event in events:
            if self._event_matches(event, event_name):
                if date_text is not None:
                    parsed = self._parse_date(date_text)
                    event["date"] = parsed.isoformat() if parsed else None
                if location is not None:
                    event["location"] = normalize_spaces(location) or None
                if status is not None:
                    event["status"] = normalize_spaces(status) or event.get("status") or "planned"
                if attendance is not None:
                    event["attendance"] = self._normalize_int(attendance)
                if budget is not None:
                    event["budget"] = self._normalize_float(budget)
                if notes is not None:
                    event["notes"] = normalize_spaces(notes) or None
                found = self._normalize_event(event)
                break
        if found:
            self.save_events(events)
        return found

    def delete_event(self, event_name: str) -> dict[str, Any] | None:
        events = self.load_events()
        kept: list[dict[str, Any]] = []
        removed = None
        for event in events:
            if self._event_matches(event, event_name) and removed is None:
                removed = self._normalize_event(event)
                continue
            kept.append(event)
        if removed is not None:
            self.save_events(kept)
        return removed

    def find_event(self, event_name: str) -> dict[str, Any] | None:
        hits = self._logged_hits_for_event(event_name)
        return hits[0] if hits else None

    def _event_matches(self, event: dict[str, Any], event_name: str) -> bool:
        low = normalize_spaces(event_name).lower()
        if not low:
            return False
        hay = " ".join([str(event.get("name") or ""), str(event.get("event_type") or ""), str(event.get("notes") or "")]).lower()
        return low in hay or slugify(low) == str(event.get("slug") or "")

    def _normalize_int(self, value: Any) -> int | None:
        try:
            return int(value) if value is not None and str(value).strip() != "" else None
        except Exception:
            return None

    def _normalize_float(self, value: Any) -> float | None:
        try:
            return round(float(value), 2) if value is not None and str(value).strip() != "" else None
        except Exception:
            return None

    def _parse_date(self, raw: Any) -> date | None:
        if not raw:
            return None
        text = str(raw).strip()
        if len(text) >= 10:
            try:
                return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
            except Exception:
                pass
        return try_parse_date(text) or relative_due_date(text)

    def upcoming_timeline(self, days: int = 30) -> str:
        today = date.today()
        end = today + timedelta(days=days)
        lines = [f"📅 **PowerBot timeline** ({today.isoformat()} → {end.isoformat()})"]
        items: list[tuple[date, str, str]] = []

        for event in self.load_events():
            d = self._parse_date(event.get("date"))
            if not d or d < today or d > end:
                continue
            extras = []
            if event.get("attendance") is not None:
                extras.append(f"attendance={event['attendance']}")
            if event.get("location"):
                extras.append(str(event["location"]))
            detail = f" — {', '.join(extras)}" if extras else ""
            items.append((d, str(event.get("name") or "event"), detail))

        for entry in self._load_note_entries():
            d = self._parse_date(entry.get("date"))
            if not d or d < today or d > end:
                continue
            label = str(entry.get("title") or entry.get("id") or "planning note").strip()
            items.append((d, f"Note: {label}", ""))

        items.sort(key=lambda x: (x[0], x[1].lower()))
        deduped: list[tuple[date, str, str]] = []
        seen = set()
        for d, label, detail in items:
            key = (d.isoformat(), label.lower())
            if key in seen:
                continue
            seen.add(key)
            deduped.append((d, label, detail))

        if not deduped:
            lines.append("- No upcoming items found in events.json or dated planning notes.")
            return "\n".join(lines)

        for d, label, detail in deduped[:15]:
            lines.append(f"- **{d.strftime('%b %d')}** — {label}{detail}")
        return "\n".join(lines)

    def event_status(self, event_name: str | None = None) -> str:
        event_name = normalize_spaces(event_name or "")
        if not event_name:
            return self.upcoming_timeline(45)

        logged = self._logged_hits_for_event(event_name)
        note_hits = self._note_hits_for_event(event_name)
        best_label = event_name
        if logged:
            best_label = str(logged[0].get("name") or event_name)
        elif note_hits:
            best_label = str(note_hits[0].get("title") or event_name)

        lines = [f"📌 **{title_case_safe(best_label)} status**"]
        if logged:
            lines.append("**Logged history**")
            for event in logged[:5]:
                details = []
                if event.get("date"):
                    details.append(str(event["date"]))
                if event.get("status"):
                    details.append(f"status={event['status']}")
                if event.get("attendance") is not None:
                    details.append(f"attendance={event['attendance']}")
                if event.get("budget") is not None:
                    details.append(f"budget={event['budget']}")
                if event.get("location"):
                    details.append(str(event["location"]))
                if event.get("notes"):
                    details.append(clip(str(event["notes"]), 110))
                lines.append(f"- {', '.join(details) if details else event.get('name', 'event')}")

        if note_hits:
            lines.append("\n**Relevant planning notes**")
            for entry in note_hits[:4]:
                title = str(entry.get("title") or entry.get("id") or "note")
                d = self._parse_date(entry.get("date"))
                d_label = d.isoformat() if d else "undated"
                snippet = clip(str(entry.get("content") or "").replace("\n", " "), 180)
                lines.append(f"- **{title}** ({d_label}) — {snippet}")

        metrics = self._summarize_event_metrics(logged)
        if metrics:
            lines.append("\n**Quick metrics**")
            lines.extend(metrics)

        if len(lines) == 1:
            lines.append("- I couldn't find a strong match. Try a more specific event name or ask for `upcoming`.")
        return "\n".join(lines)

    def event_snapshot(self, event_name: str | None = None) -> dict[str, Any]:
        event_name = normalize_spaces(event_name or "")
        logged = self._logged_hits_for_event(event_name) if event_name else self.load_events()
        notes = self._note_hits_for_event(event_name) if event_name else self._load_note_entries()
        return {
            "event": event_name or None,
            "logged_count": len(logged),
            "notes_count": len(notes),
            "latest_logged": logged[0] if logged else None,
        }

    def render_dashboard(self) -> str:
        today = date.today()
        events = self.load_events()
        note_entries = self._load_note_entries()
        upcoming_notes = [n for n in note_entries if self._parse_date(n.get("date")) and self._parse_date(n.get("date")) >= today]
        lines = ["📆 **PowerBot event dashboard**"]
        lines.append(f"- Logged event entries: **{len(events)}**")
        lines.append(f"- Future planning notes: **{len(upcoming_notes)}**")
        if events:
            latest = sorted(events, key=lambda e: ((self._parse_date(e.get("date")) or date.min), str(e.get("name") or "").lower()), reverse=True)[0]
            lines.append(f"- Latest logged event: **{title_case_safe(latest.get('name'))}** ({latest.get('date') or 'undated'})")
        timeline = self.upcoming_timeline(30)
        tail = timeline.splitlines()[1:6]
        if tail:
            lines.append("\n**Next 30 days**")
            lines.extend(tail)
        return "\n".join(lines)

    def _logged_hits_for_event(self, event_name: str) -> list[dict[str, Any]]:
        low = event_name.lower()
        hits: list[tuple[int, dict[str, Any]]] = []
        for event in self.load_events():
            hay = " ".join(
                [
                    str(event.get("name") or ""),
                    str(event.get("event_type") or ""),
                    str(event.get("notes") or ""),
                ]
            )
            score = text_score(low, hay)
            if score > 0:
                hits.append((score, event))
        hits.sort(key=lambda item: (-item[0], item[1].get("date") or ""))
        return [event for _, event in hits]

    def _note_hits_for_event(self, event_name: str) -> list[dict[str, Any]]:
        low = event_name.lower()
        hits: list[tuple[int, dict[str, Any]]] = []
        for entry in self._load_note_entries():
            hay = f"{entry.get('title','')}\n{entry.get('content','')}"
            score = text_score(low, hay)
            if score > 0:
                hits.append((score, entry))
        hits.sort(key=lambda item: (-item[0], str(item[1].get("date") or "")))
        return [entry for _, entry in hits]

    def _load_note_entries(self) -> list[dict[str, Any]]:
        notes = safe_read_json(self.planning_notes_path, {})
        entries = notes.get("entries") if isinstance(notes, dict) else []
        return [entry for entry in entries if isinstance(entry, dict)] if isinstance(entries, list) else []

    def _summarize_event_metrics(self, logged: list[dict[str, Any]]) -> list[str]:
        if not logged:
            return []
        attendance_values = [int(e["attendance"]) for e in logged if isinstance(e.get("attendance"), int)]
        budget_values = [float(e["budget"]) for e in logged if isinstance(e.get("budget"), (int, float))]
        lines = [f"- Logged entries: **{len(logged)}**"]
        if attendance_values:
            avg = sum(attendance_values) / len(attendance_values)
            lines.append(f"- Average attendance: **{avg:.1f}**")
            lines.append(f"- Best attendance: **{max(attendance_values)}**")
        if budget_values:
            avg_budget = sum(budget_values) / len(budget_values)
            lines.append(f"- Average budget: **${avg_budget:.2f}**")
        return lines
