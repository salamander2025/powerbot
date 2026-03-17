from __future__ import annotations

from .events_engine import EventsEngine
from .tasks_engine import TasksEngine
from .utils import title_case_safe


class AdvisorEngine:
    DEFAULT_KNOWN_EVENTS = ["welcome-week", "general-meeting", "social", "workshop", "trivia"]

    def __init__(
        self,
        tasks_engine: TasksEngine,
        events_engine: EventsEngine,
        known_events: list[str] | None = None,
    ):
        self.tasks_engine = tasks_engine
        self.events_engine = events_engine
        self._known_events = list(known_events) if known_events else list(self.DEFAULT_KNOWN_EVENTS)

    def advise(self, query: str, event_name: str | None = None) -> str:
        event_name = (event_name or "").strip() or self._guess_event_name(query)
        open_tasks = self.tasks_engine.query_open_tasks(event=event_name or None)
        high = self.tasks_engine.query_open_tasks(event=event_name or None, priority="high")
        due_week = self.tasks_engine.query_open_tasks(event=event_name or None, due_scope="this week")
        derived = self.tasks_engine._derive_from_planning_notes(event=event_name or None)

        lines = ["🧭 **PowerBot advisor**"]
        if event_name:
            lines.append(f"Focus: **{title_case_safe(event_name)}**")

        if open_tasks or derived:
            lines.append("\n**Recommended next steps**")
            ranked = []
            ranked.extend(high[:3])
            ranked.extend([t for t in due_week if t not in ranked][:2])
            ranked.extend([t for t in open_tasks if t not in ranked][:4])
            seen_titles = set()
            idx = 1
            for task in ranked[:6]:
                title = str(task.get("title") or "").strip()
                if not title or title.lower() in seen_titles:
                    continue
                seen_titles.add(title.lower())
                owner = f" ({task['owner']})" if task.get("owner") else ""
                due = f" — due {task['due_date']}" if task.get("due_date") else ""
                priority = " [HIGH]" if task.get("priority") == "high" else ""
                lines.append(f"{idx}. {title}{owner}{priority}{due}")
                idx += 1
            for item in derived[:4]:
                if item.lower() in seen_titles:
                    continue
                lines.append(f"{idx}. {item}")
                idx += 1
                if idx > 6:
                    break
            lines.append("\nBest move: keep the top priorities as tracked tasks so they stop living only in chat history.")
            return "\n".join(lines)

        if event_name:
            lines.append(self.events_engine.event_status(event_name))
            lines.append("\nRecommended next move: create 2–3 concrete tracked tasks from the event status above.")
            return "\n".join(lines)

        lines.append("- I don't have enough explicit action items yet.")
        lines.append("- Best next step: add a few concrete tasks or ask about a specific event.")
        return "\n".join(lines)

    def _guess_event_name(self, query: str) -> str | None:
        q = (query or "").lower()
        for item in self._known_events:
            if item and item.lower() in q:
                return item
        return None
