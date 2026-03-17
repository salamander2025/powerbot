from __future__ import annotations

import re

from .advisor_engine import AdvisorEngine
from .events_engine import EventsEngine
from .intents import IntentRouter
from .meeting_engine import MeetingEngine
from .memory_engine import MemoryEngine
from .models import HubResult
from .tasks_engine import TasksEngine
from .utils import normalize_spaces


class PowerBotHubService:
    def __init__(
        self,
        *,
        tasks_path: str,
        planning_notes_path: str,
        events_path: str,
        archive_path: str,
        club_memory_path: str,
        eboard_log_path: str,
        owner_hints: list[str] | tuple[str, ...] | None = None,
        known_events: list[str] | None = None,
    ):
        self.router = IntentRouter(owner_hints=owner_hints, known_events=known_events)
        self.tasks = TasksEngine(tasks_path, planning_notes_path)
        self.events = EventsEngine(events_path, planning_notes_path)
        self.memory = MemoryEngine(planning_notes_path, archive_path, club_memory_path)
        self.meetings = MeetingEngine(archive_path, eboard_log_path)
        self.advisor = AdvisorEngine(self.tasks, self.events, known_events=known_events)

    def handle(self, text: str, *, user_name: str = "Member") -> HubResult:
        match = self.router.route(text)
        entities = dict(match.entities)
        owner = entities.get("owner") or self._normalize_owner_from_query(text, user_name)
        event = entities.get("event")
        due_scope = self._normalize_due_scope(text, entities.get("due"))
        priority = entities.get("priority") or self._normalize_priority(text)
        status = entities.get("status") or self._normalize_status(text)

        if match.intent == "help":
            return HubResult(self.help_text(), "help")

        if match.intent == "dashboard":
            event_dash = self.events.render_dashboard()
            task_dash = self.tasks.render_dashboard(owner=owner if "my" in normalize_spaces(text).lower() else None)
            return HubResult(f"{task_dash}\n\n{event_dash}", match.intent)

        if match.intent == "task_add":
            title = entities.get("title") or text
            title, title_event, title_due, title_priority = self._extract_inline_task_metadata(title)
            event = event or title_event
            due = entities.get("due") or title_due
            priority = priority or title_priority
            task = self.tasks.add_task(
                title,
                owner=entities.get("owner") or owner,
                source="hub",
                created_by=user_name,
                due=due,
                priority=priority,
                event=event,
            )
            msg = f"✅ Added task **#{task['id']}** — {task['title']}"
            if task.get("owner"):
                msg += f" (owner: {task['owner']})"
            if task.get("priority") and task.get("priority") != "medium":
                msg += f" • {str(task['priority']).title()} priority"
            if task.get("due_date"):
                msg += f" • due {task['due_date']}"
            if task.get("event"):
                msg += f" • event={task['event']}"
            task_owner = normalize_spaces(str(task.get("owner") or ""))
            if task_owner and task_owner.lower() != normalize_spaces(user_name).lower():
                msg += f"\nNote: This task is assigned to {task_owner}. Use `!pb due this week` or `!pb list all` to view all tasks."
            msg += "\nUse `!pb my tasks`, `!pb due this week`, or `!pb complete task <id>` next."
            return HubResult(msg, match.intent, {"task_id": task["id"]})

        if match.intent == "task_complete":
            task_id = int(entities.get("task_id") or 0)
            task = self.tasks.complete_task(task_id, completed_by=user_name)
            if not task:
                return HubResult(f"❌ I couldn't find task **#{task_id}**.", match.intent)
            return HubResult(f"✅ Completed task **#{task_id}** — {task.get('title', 'Untitled')}", match.intent)

        if match.intent == "task_reopen":
            task_id = int(entities.get("task_id") or 0)
            task = self.tasks.reopen_task(task_id)
            if not task:
                return HubResult(f"❌ I couldn't find task **#{task_id}**.", match.intent)
            return HubResult(f"🔄 Reopened task **#{task_id}** — {task.get('title', 'Untitled')}", match.intent)

        if match.intent == "task_cancel":
            task_id = int(entities.get("task_id") or 0)
            task = self.tasks.cancel_task(task_id)
            if not task:
                return HubResult(f"❌ I couldn't find task **#{task_id}**.", match.intent)
            return HubResult(f"🚫 Cancelled task **#{task_id}** — {task.get('title', 'Untitled')}", match.intent)

        if match.intent == "task_delete":
            task_id = int(entities.get("task_id") or 0)
            task = self.tasks.delete_task(task_id)
            if not task:
                return HubResult(f"❌ I couldn't find task **#{task_id}**.", match.intent)
            return HubResult(f"🗑️ Deleted task **#{task_id}** — {task.get('title', 'Untitled')}", match.intent)

        if match.intent == "task_update":
            task_id = int(entities.get("task_id") or 0)
            task = self.tasks.update_task(
                task_id,
                owner=entities.get("owner"),
                due=entities.get("due"),
                priority=entities.get("priority"),
                event=entities.get("event"),
                title=entities.get("title"),
                notes=entities.get("notes"),
            )
            if not task:
                return HubResult(f"❌ I couldn't find task **#{task_id}**.", match.intent)
            return HubResult(f"✏️ Updated task **#{task_id}** — {self.tasks._render_task_line(task)}", match.intent)

        if match.intent == "task_sync":
            items = self.meetings.extract_action_items()
            created = self.tasks.import_action_items(items, created_by=user_name)
            lines = ["🔁 **Imported action items**"]
            lines.append(f"- New tracked tasks: **{len(created)}**")
            if created:
                for task in created[:8]:
                    lines.append(self.tasks._render_task_line(task))
            else:
                lines.append("- No new action items were imported. Recent meeting items were already tracked or nothing actionable was detected.")
            return HubResult("\n".join(lines), match.intent, {"created": len(created)})

        if match.intent == "task_query":
            rendered = self.tasks.render_tasks(owner=owner, event=event, due_scope=due_scope, priority=priority, status=status)
            qlow = normalize_spaces(text).lower()
            if any(x in qlow for x in ["my tasks", "my todo", "my to-do"]):
                rendered = rendered.replace(
                    "- No tasks match that filter right now.",
                    "No tasks assigned to you right now.\nTip: Try `!pb due this week` or `!pb list all` to see all tasks.",
                )
            return HubResult(rendered, match.intent, {"owner": owner, "event": event, "due_scope": due_scope, "priority": priority, "status": status})

        if match.intent == "event_add":
            name = entities.get("name") or event or text
            created = self.events.add_event(
                name,
                date_text=entities.get("date") or entities.get("due"),
                location=entities.get("location"),
                logged_by=user_name,
            )
            msg = f"📅 Added event **{created['name']}**"
            if created.get("date"):
                msg += f" • {created['date']}"
            if created.get("location"):
                msg += f" • {created['location']}"
            msg += "\nUse `!pb status of <event>` or `!pb set budget for <event> to 150` next."
            return HubResult(msg, match.intent, {"event": created.get("name")})

        if match.intent == "event_update":
            event_name = entities.get("event") or entities.get("name") or event
            if not event_name:
                return HubResult("❌ I need the event name to update it.", match.intent)
            updated = self.events.update_event(
                event_name,
                date_text=entities.get("date"),
                location=entities.get("location"),
                status=entities.get("status"),
                attendance=self._safe_int(entities.get("attendance")),
                budget=self._safe_float(entities.get("budget")),
                notes=entities.get("notes"),
            )
            if not updated:
                return HubResult(f"❌ I couldn't find an event match for **{event_name}**.", match.intent)
            return HubResult(f"✏️ Updated event **{updated['name']}**\n{self.events.event_status(updated['name'])}", match.intent, {"event": updated['name']})

        if match.intent == "event_delete":
            event_name = entities.get("event") or entities.get("name") or event
            if not event_name:
                return HubResult("❌ I need the event name to delete it.", match.intent)
            removed = self.events.delete_event(event_name)
            if not removed:
                return HubResult(f"❌ I couldn't find an event match for **{event_name}**.", match.intent)
            return HubResult(f"🗑️ Deleted event **{removed['name']}**", match.intent, {"event": removed['name']})

        if match.intent == "timeline":
            days = 30
            return HubResult(self.events.upcoming_timeline(days), match.intent, {"days": days})

        if match.intent == "event_status":
            text_low = normalize_spaces(text).lower()
            if "assigned" in text_low:
                if event:
                    return HubResult(self.tasks.render_tasks(event=event), "task_query", {"event": event})
                if owner:
                    return HubResult(self.tasks.render_tasks(owner=owner), "task_query", {"owner": owner})
            event_text = self.events.event_status(event)
            task_snapshot = self.tasks.render_status_snapshot(event=event) if event else None
            combined = event_text if not task_snapshot else f"{event_text}\n\n{task_snapshot}"
            return HubResult(combined, match.intent, {"event": event})

        if match.intent == "meeting_summary":
            return HubResult(self.meetings.summarize_recent(), match.intent)

        if match.intent == "advisor":
            return HubResult(self.advisor.advise(text, event), match.intent, {"event": event})

        return HubResult(self.memory.lookup(text), "memory_lookup")

    def help_text(self) -> str:
        return (
            "⚡ **PowerBot Command Hub**\n"
            "Talk to PowerBot naturally with `!pb ...`.\n\n"
            "**Best examples**\n"
            "- `!pb my tasks`\n"
            "- `!pb add task for President to confirm room by Friday high priority for welcome-week`\n"
            "- `!pb due this week`\n"
            "- `!pb complete task 1`\n"
            "- `!pb cancel task 3`\n"
            "- `!pb reassign task 1 to Treasurer`\n"
            "- `!pb summarize the last eboard discussion`\n"
            "- `!pb sync action items`\n"
            "- `!pb add event welcome-week on Friday at Student Center`\n"
            "- `!pb set notes for welcome-week to Order snacks after flyer approval`\n"
            "- `!pb set budget for welcome-week to 150`\n"
            "- `!pb status of welcome-week`\n"
            "- `!pb dashboard`\n"
            "- `!pb upcoming`\n"
            "- `!pb who was supposed to confirm the room`\n\n"
            "Use one hub command with intent routing, tracked tasks, event status, summaries, memory lookup, and advisor mode."
        )

    def _normalize_owner_from_query(self, text: str, fallback: str) -> str | None:
        q = normalize_spaces(text).lower()
        if any(x in q for x in ["my tasks", "what should i do", "what am i supposed to do", "my dashboard"]):
            return fallback
        return None

    def _normalize_due_scope(self, text: str, due: str | None) -> str | None:
        q = normalize_spaces(text).lower()
        due_low = normalize_spaces(due or "").lower()
        if "overdue" in q:
            return "overdue"
        if "this week" in due_low or "due this week" in q:
            return "this week"
        return None

    def _normalize_priority(self, text: str) -> str | None:
        q = normalize_spaces(text).lower()
        if "high priority" in q or "urgent" in q:
            return "high"
        if "low priority" in q:
            return "low"
        if "medium priority" in q:
            return "medium"
        return None

    def _normalize_status(self, text: str) -> str | None:
        q = normalize_spaces(text).lower()
        if "completed tasks" in q or "done tasks" in q:
            return "done"
        if "cancelled tasks" in q or "canceled tasks" in q:
            return "cancelled"
        return None

    def _extract_inline_task_metadata(self, title: str) -> tuple[str, str | None, str | None, str | None]:
        text = normalize_spaces(title)
        event = None
        due = None
        priority = None

        m_event = None
        for pattern in (r"\bfor ([A-Za-z0-9][A-Za-z0-9 &\-']{2,40})$", r"\bfor ([A-Za-z0-9][A-Za-z0-9 &\-']{2,40})\b"):
            m_event = re.search(pattern, text, flags=re.IGNORECASE)
            if m_event:
                event = normalize_spaces(m_event.group(1))
                text = normalize_spaces(text[: m_event.start()] + text[m_event.end() :])
                break

        m_due = re.search(r"\bby ((?:\d{4}-\d{2}-\d{2})|(?:\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)|(?:today|tomorrow|this week|next week|monday|tuesday|wednesday|thursday|friday|saturday|sunday|[A-Za-z]{3,9} \d{1,2}(?: \d{4})?))\b", text, flags=re.IGNORECASE)
        if m_due:
            due = normalize_spaces(m_due.group(1))
            text = normalize_spaces(text[: m_due.start()] + text[m_due.end() :])

        if "high priority" in text.lower() or "urgent" in text.lower():
            priority = "high"
            text = normalize_spaces(text.replace("high priority", "").replace("urgent", ""))
        elif "low priority" in text.lower():
            priority = "low"
            text = normalize_spaces(text.replace("low priority", ""))
        elif "medium priority" in text.lower():
            priority = "medium"
            text = normalize_spaces(text.replace("medium priority", ""))

        return text, event, due, priority

    def _safe_int(self, value: str | None) -> int | None:
        try:
            return int(value) if value is not None else None
        except Exception:
            return None

    def _safe_float(self, value: str | None) -> float | None:
        try:
            return float(value) if value is not None else None
        except Exception:
            return None
