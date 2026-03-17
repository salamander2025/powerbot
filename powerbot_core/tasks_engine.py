from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from .utils import clip, normalize_spaces, relative_due_date, safe_read_json, safe_write_json, slugify, try_parse_date, utcnow_iso


class TasksEngine:
    def __init__(self, tasks_path: str, planning_notes_path: str):
        self.tasks_path = tasks_path
        self.planning_notes_path = planning_notes_path

    def ensure_store(self) -> None:
        data = safe_read_json(self.tasks_path, None)
        if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
            safe_write_json(self.tasks_path, self._empty_store())
            return
        if data.get("schema") != "powerbot.tasks.v2":
            tasks = [self._normalize_task(t) for t in data.get("tasks", []) if isinstance(t, dict)]
            safe_write_json(
                self.tasks_path,
                {
                    "schema": "powerbot.tasks.v2",
                    "last_updated": utcnow_iso(),
                    "tasks": tasks,
                },
            )

    def _empty_store(self) -> dict[str, Any]:
        return {
            "schema": "powerbot.tasks.v2",
            "last_updated": utcnow_iso(),
            "tasks": [],
        }

    def _normalize_task(self, task: dict[str, Any]) -> dict[str, Any]:
        due_date = task.get("due_date") or task.get("due")
        parsed_due = None
        if isinstance(due_date, str):
            parsed_due = try_parse_date(due_date) or relative_due_date(due_date)
        status = str(task.get("status") or "open").lower()
        if status not in {"open", "done", "cancelled"}:
            status = "open"
        priority = str(task.get("priority") or "medium").lower()
        if priority not in {"low", "medium", "high"}:
            priority = "medium"
        return {
            "id": int(task.get("id") or 0),
            "slug": task.get("slug") or slugify(str(task.get("title") or "task")),
            "title": normalize_spaces(str(task.get("title") or "Untitled task")),
            "owner": normalize_spaces(str(task.get("owner") or "")) or None,
            "status": status,
            "priority": priority,
            "event": normalize_spaces(str(task.get("event") or "")) or None,
            "due_date": parsed_due.isoformat() if parsed_due else None,
            "notes": normalize_spaces(str(task.get("notes") or "")) or None,
            "source": str(task.get("source") or "hub"),
            "created_at": str(task.get("created_at") or utcnow_iso()),
            "created_by": normalize_spaces(str(task.get("created_by") or "")) or None,
            "updated_at": str(task.get("updated_at") or task.get("created_at") or utcnow_iso()),
            "completed_at": str(task.get("completed_at") or "") or None,
            "completed_by": normalize_spaces(str(task.get("completed_by") or "")) or None,
        }

    def load_tasks(self) -> list[dict[str, Any]]:
        self.ensure_store()
        data = safe_read_json(self.tasks_path, self._empty_store())
        tasks = data.get("tasks") if isinstance(data, dict) else []
        if not isinstance(tasks, list):
            return []
        out = [self._normalize_task(t) for t in tasks if isinstance(t, dict)]
        if any(int(t.get("id") or 0) == 0 for t in out):
            next_id = 1
            for task in out:
                if int(task.get("id") or 0) <= 0:
                    task["id"] = next_id
                    next_id += 1
                else:
                    next_id = max(next_id, int(task["id"]) + 1)
            self.save_tasks(out)
        return out

    def save_tasks(self, tasks: list[dict[str, Any]]) -> None:
        payload = {
            "schema": "powerbot.tasks.v2",
            "last_updated": utcnow_iso(),
            "tasks": tasks,
        }
        safe_write_json(self.tasks_path, payload)

    def add_task(
        self,
        title: str,
        owner: str | None = None,
        *,
        source: str = "hub",
        created_by: str | None = None,
        due: str | None = None,
        priority: str | None = None,
        event: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        title = normalize_spaces(title).rstrip(".")
        owner = normalize_spaces(owner or "") or None
        priority = (priority or "medium").strip().lower()
        if priority not in {"low", "medium", "high"}:
            priority = "medium"
        due_date = try_parse_date(due or "") or relative_due_date(due or "")
        event = normalize_spaces(event or "") or None
        notes = normalize_spaces(notes or "") or None
        tasks = self.load_tasks()
        next_id = max((int(t.get("id") or 0) for t in tasks), default=0) + 1
        now = utcnow_iso()
        task = {
            "id": next_id,
            "slug": slugify(title),
            "title": title,
            "owner": owner,
            "status": "open",
            "priority": priority,
            "event": event,
            "due_date": due_date.isoformat() if due_date else None,
            "notes": notes,
            "source": source,
            "created_at": now,
            "created_by": created_by,
            "updated_at": now,
            "completed_at": None,
            "completed_by": None,
        }
        tasks.append(task)
        self.save_tasks(tasks)
        return task

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        for task in self.load_tasks():
            if int(task.get("id") or 0) == int(task_id):
                return task
        return None

    def complete_task(self, task_id: int, *, completed_by: str | None = None) -> dict[str, Any] | None:
        tasks = self.load_tasks()
        found = None
        for task in tasks:
            if int(task.get("id") or 0) == int(task_id):
                task["status"] = "done"
                task["completed_at"] = utcnow_iso()
                task["completed_by"] = completed_by
                task["updated_at"] = utcnow_iso()
                found = task
                break
        if found:
            self.save_tasks(tasks)
        return found

    def reopen_task(self, task_id: int) -> dict[str, Any] | None:
        tasks = self.load_tasks()
        found = None
        for task in tasks:
            if int(task.get("id") or 0) == int(task_id):
                task["status"] = "open"
                task["completed_at"] = None
                task["completed_by"] = None
                task["updated_at"] = utcnow_iso()
                found = task
                break
        if found:
            self.save_tasks(tasks)
        return found

    def delete_task(self, task_id: int) -> dict[str, Any] | None:
        tasks = self.load_tasks()
        kept = []
        removed = None
        for task in tasks:
            if int(task.get("id") or 0) == int(task_id):
                removed = task
                continue
            kept.append(task)
        if removed is not None:
            self.save_tasks(kept)
        return removed

    def cancel_task(self, task_id: int) -> dict[str, Any] | None:
        tasks = self.load_tasks()
        found = None
        for task in tasks:
            if int(task.get("id") or 0) == int(task_id):
                task["status"] = "cancelled"
                task["completed_at"] = None
                task["completed_by"] = None
                task["updated_at"] = utcnow_iso()
                found = task
                break
        if found:
            self.save_tasks(tasks)
        return found

    def update_task(
        self,
        task_id: int,
        *,
        owner: str | None = None,
        due: str | None = None,
        priority: str | None = None,
        event: str | None = None,
        title: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any] | None:
        tasks = self.load_tasks()
        found = None
        for task in tasks:
            if int(task.get("id") or 0) != int(task_id):
                continue
            if owner is not None:
                task["owner"] = normalize_spaces(owner) or None
            if due is not None:
                parsed = try_parse_date(due) or relative_due_date(due)
                task["due_date"] = parsed.isoformat() if parsed else None
            if priority is not None:
                pr = normalize_spaces(priority).lower()
                if pr in {"low", "medium", "high"}:
                    task["priority"] = pr
            if event is not None:
                task["event"] = normalize_spaces(event) or None
            if title is not None:
                task["title"] = normalize_spaces(title).rstrip(".") or task["title"]
                task["slug"] = slugify(task["title"])
            if notes is not None:
                task["notes"] = normalize_spaces(notes) or None
            task["updated_at"] = utcnow_iso()
            found = task
            break
        if found:
            self.save_tasks(tasks)
        return found

    def query_open_tasks(
        self,
        owner: str | None = None,
        *,
        event: str | None = None,
        due_scope: str | None = None,
        priority: str | None = None,
        include_done: bool = False,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        owner_low = normalize_spaces(owner or "").lower()
        event_low = normalize_spaces(event or "").lower()
        due_scope = normalize_spaces(due_scope or "").lower()
        priority = normalize_spaces(priority or "").lower()
        status = normalize_spaces(status or "").lower()
        today = date.today()
        week_end = today + timedelta(days=max(0, 6 - today.weekday()))
        out = []
        for task in self.load_tasks():
            task_status = str(task.get("status") or "open").lower()
            if status:
                if task_status != status:
                    continue
            elif not include_done and task_status != "open":
                continue
            if owner_low and owner_low not in str(task.get("owner") or "").lower():
                continue
            task_event = str(task.get("event") or "")
            task_notes = str(task.get("notes") or "")
            task_title = str(task.get("title") or "")
            if event_low and event_low not in task_event.lower() and event_low not in task_title.lower() and event_low not in task_notes.lower():
                continue
            if priority and priority != str(task.get("priority") or "medium").lower():
                continue
            due_raw = task.get("due_date")
            due_date = try_parse_date(str(due_raw)) if due_raw else None
            if due_scope == "this week" and not (due_date and today <= due_date <= week_end):
                continue
            if due_scope == "overdue" and not (due_date and due_date < today):
                continue
            out.append(task)
        out.sort(key=self._sort_key)
        return out

    def render_tasks(
        self,
        *,
        owner: str | None = None,
        event: str | None = None,
        due_scope: str | None = None,
        priority: str | None = None,
        include_derived: bool = True,
        status: str | None = None,
    ) -> str:
        explicit = self.query_open_tasks(owner=owner, event=event, due_scope=due_scope, priority=priority, status=status)
        derived: list[str] = []
        if include_derived and (status or "open") == "open":
            derived = self._derive_from_planning_notes(owner=owner, event=event)

        scope_parts = []
        if owner:
            scope_parts.append(owner)
        if event:
            scope_parts.append(event.title())
        if due_scope:
            scope_parts.append(due_scope.title())
        if priority:
            scope_parts.append(f"{priority.title()} Priority")
        if status and status != "open":
            scope_parts.append(status.title())
        label = " • ".join(scope_parts) if scope_parts else "E-board"

        lead = "Current tasks"
        if status == "done":
            lead = "Completed tasks"
        elif status == "cancelled":
            lead = "Cancelled tasks"
        lines: list[str] = [f"🧩 **{lead} — {label}**"]
        if explicit:
            for task in explicit[:15]:
                lines.append(self._render_task_line(task))
        else:
            lines.append("- No tasks match that filter right now.")

        if derived and not explicit:
            lines.append("\n**Likely action items from planning memory**")
            for item in derived[:8]:
                lines.append(f"- {item}")

        if not explicit and not derived:
            lines.append("- Try: `!pb add task for President to confirm the room by Friday high priority`")
        return "\n".join(lines)

    def render_status_snapshot(self, *, event: str | None = None) -> str:
        open_tasks = self.query_open_tasks(event=event)
        high = self.query_open_tasks(event=event, priority="high")
        due_week = self.query_open_tasks(event=event, due_scope="this week")
        overdue = self.query_open_tasks(event=event, due_scope="overdue")
        done = self.query_open_tasks(event=event, status="done")
        lines = ["📋 **Task snapshot**"]
        if event:
            lines[0] = f"📋 **Task snapshot — {event.title()}**"
        lines.append(f"- Open: **{len(open_tasks)}**")
        lines.append(f"- High priority: **{len(high)}**")
        lines.append(f"- Due this week: **{len(due_week)}**")
        lines.append(f"- Overdue: **{len(overdue)}**")
        lines.append(f"- Completed: **{len(done)}**")
        if open_tasks:
            lines.append("\n**Top open tasks**")
            for task in open_tasks[:5]:
                lines.append(self._render_task_line(task))
        return "\n".join(lines)

    def render_dashboard(self, *, owner: str | None = None) -> str:
        owner_label = owner or "E-board"
        open_tasks = self.query_open_tasks(owner=owner)
        high = self.query_open_tasks(owner=owner, priority="high")
        due_week = self.query_open_tasks(owner=owner, due_scope="this week")
        overdue = self.query_open_tasks(owner=owner, due_scope="overdue")
        done = self.query_open_tasks(owner=owner, status="done")
        lines = [f"📊 **PowerBot task dashboard — {owner_label}**"]
        lines.append(f"- Open tasks: **{len(open_tasks)}**")
        lines.append(f"- High priority: **{len(high)}**")
        lines.append(f"- Due this week: **{len(due_week)}**")
        lines.append(f"- Overdue: **{len(overdue)}**")
        lines.append(f"- Completed tracked tasks: **{len(done)}**")
        if high:
            lines.append("\n**Top priorities**")
            for task in high[:5]:
                lines.append(self._render_task_line(task))
        elif open_tasks:
            lines.append("\n**Next up**")
            for task in open_tasks[:5]:
                lines.append(self._render_task_line(task))
        return "\n".join(lines)


    def import_action_items(self, items: list[dict[str, str]], *, created_by: str | None = None) -> list[dict[str, Any]]:
        created: list[dict[str, Any]] = []
        existing = self.load_tasks()
        for item in items:
            if not isinstance(item, dict):
                continue
            owner = normalize_spaces(str(item.get("owner") or "")) or None
            title = normalize_spaces(str(item.get("title") or "")).rstrip(".")
            if not title:
                continue
            key = (owner or "", title.lower())
            duplicate = False
            for task in existing:
                tkey = ((normalize_spaces(str(task.get("owner") or "")) or ""), normalize_spaces(str(task.get("title") or "")).lower())
                if key == tkey and str(task.get("status") or "open").lower() == "open":
                    duplicate = True
                    break
            if duplicate:
                continue
            new_task = self.add_task(title, owner=owner, source="meeting_sync", created_by=created_by, notes=f"Imported from meeting action items ({item.get('timestamp') or 'recent'})")
            existing.append(new_task)
            created.append(new_task)
        return created

    def _render_task_line(self, task: dict[str, Any]) -> str:
        meta = []
        if task.get("owner"):
            meta.append(str(task["owner"]))
        if task.get("priority") and task.get("priority") != "medium":
            meta.append(f"{str(task['priority']).title()} priority")
        if task.get("due_date"):
            meta.append(f"due {task['due_date']}")
        if task.get("event"):
            meta.append(f"event={task['event']}")
        if task.get("status") == "done":
            meta.append("done")
        elif task.get("status") == "cancelled":
            meta.append("cancelled")
        meta_text = f" ({'; '.join(meta)})" if meta else ""
        note = f" — {clip(str(task.get('notes') or ''), 70)}" if task.get("notes") else ""
        return f"- **#{task['id']}** {task.get('title', 'Untitled')}{meta_text}{note}"

    def _derive_from_planning_notes(self, *, owner: str | None = None, event: str | None = None) -> list[str]:
        notes = safe_read_json(self.planning_notes_path, {})
        entries = notes.get("entries") if isinstance(notes, dict) else []
        if not isinstance(entries, list):
            return []
        owner_low = normalize_spaces(owner or "").lower()
        event_low = normalize_spaces(event or "").lower()
        hits: list[str] = []
        verbs = ("email", "confirm", "post", "finalize", "assign", "buy", "order", "handle", "submit", "create", "set up", "advertise", "update")
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            title = str(entry.get("title") or "")
            content = str(entry.get("content") or "")
            hay = f"{title}\n{content}".lower()
            if event_low and event_low not in hay:
                continue
            for raw in content.splitlines():
                line = raw.strip(" -*•\t")
                if not line:
                    continue
                low = line.lower()
                if owner_low and owner_low not in low and owner_low not in title.lower():
                    continue
                if not any(v in low for v in verbs):
                    continue
                cleaned = re.sub(r"\s+", " ", line).strip()
                if cleaned and cleaned not in hits:
                    hits.append(cleaned)
        return hits[:12]

    def _sort_key(self, task: dict[str, Any]) -> tuple[int, str, int]:
        priority_rank = {"high": 0, "medium": 1, "low": 2}
        due_date = task.get("due_date") or "9999-12-31"
        return (priority_rank.get(str(task.get("priority") or "medium"), 1), due_date, int(task.get("id") or 0))
