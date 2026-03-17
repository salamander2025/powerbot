from __future__ import annotations

import re
from dataclasses import dataclass

from .utils import normalize_spaces


@dataclass(slots=True)
class IntentMatch:
    intent: str
    confidence: float
    entities: dict[str, str]


class IntentRouter:
    """Generic defaults for public/starter use; override via config owner_hints and known_events."""
    DEFAULT_OWNER_HINTS = ("President", "Treasurer", "Secretary", "Vice President")
    DEFAULT_KNOWN_EVENTS = ["welcome-week", "general-meeting", "social", "workshop", "trivia"]

    def __init__(self, owner_hints: tuple[str, ...] | list[str] | None = None, known_events: list[str] | None = None):
        self._owner_hints = tuple(owner_hints) if owner_hints else self.DEFAULT_OWNER_HINTS
        self._known_events = list(known_events) if known_events is not None else list(self.DEFAULT_KNOWN_EVENTS)

    def route(self, text: str) -> IntentMatch:
        q = normalize_spaces(text)
        low = q.lower()
        entities: dict[str, str] = {}

        if not q:
            return IntentMatch("help", 1.0, entities)

        # Explicit alias: `!pb list all` -> all open tasks (no owner filter)
        if low in {"list all", "list all tasks"}:
            entities.update(self._extract_common_entities(q))
            return IntentMatch("task_query", 0.93, entities)

        # Task creation
        for pattern in (
            r"^(?:add|create|make) (?:a )?task for (?P<owner>[A-Za-z][A-Za-z .'-]{0,30}) to (?P<title>.+)$",
            r"^(?:assign|remind) (?P<owner>[A-Za-z][A-Za-z .'-]{0,30}) to (?P<title>.+)$",
            r"^(?:add|create|make) (?:a )?task(?: to)? (?P<title>.+)$",
        ):
            m = re.match(pattern, q, flags=re.IGNORECASE)
            if m:
                entities = {k: v.strip() for k, v in m.groupdict(default="").items() if v and v.strip()}
                entities.update(self._extract_common_entities(q))
                return IntentMatch("task_add", 0.99, entities)

        # Task lifecycle
        for pattern in (
            r"^(?:complete|finish|close|done with|mark done|mark complete) task #?(?P<task_id>\d+)$",
            r"^(?:complete|finish|close|mark done|mark complete) #?(?P<task_id>\d+)$",
        ):
            m = re.match(pattern, q, flags=re.IGNORECASE)
            if m:
                return IntentMatch("task_complete", 0.99, {"task_id": m.group("task_id")})

        for pattern in (
            r"^(?:reopen|undo|mark open) task #?(?P<task_id>\d+)$",
            r"^(?:reopen|undo|mark open) #?(?P<task_id>\d+)$",
        ):
            m = re.match(pattern, q, flags=re.IGNORECASE)
            if m:
                return IntentMatch("task_reopen", 0.99, {"task_id": m.group("task_id")})

        for pattern in (
            r"^(?:cancel|drop|void) task #?(?P<task_id>\d+)$",
            r"^(?:cancel|drop|void) #?(?P<task_id>\d+)$",
        ):
            m = re.match(pattern, q, flags=re.IGNORECASE)
            if m:
                return IntentMatch("task_cancel", 0.99, {"task_id": m.group("task_id")})

        for pattern in (
            r"^(?:delete|remove) task #?(?P<task_id>\d+)$",
            r"^(?:delete|remove) #?(?P<task_id>\d+)$",
        ):
            m = re.match(pattern, q, flags=re.IGNORECASE)
            if m:
                return IntentMatch("task_delete", 0.99, {"task_id": m.group("task_id")})

        for pattern in (
            r"^(?:reassign|assign) task #?(?P<task_id>\d+) to (?P<owner>[A-Za-z][A-Za-z .'-]{0,30})$",
            r"^(?:set|change) priority (?:of )?task #?(?P<task_id>\d+) to (?P<priority>high|medium|low)$",
            r"^(?:change|set|move) due (?:date )?(?:of )?task #?(?P<task_id>\d+) to (?P<due>.+)$",
            r"^(?:rename|retitle) task #?(?P<task_id>\d+) to (?P<title>.+)$",
            r"^(?:add|set|change) notes? (?:for|of) task #?(?P<task_id>\d+) to (?P<notes>.+)$",
        ):
            m = re.match(pattern, q, flags=re.IGNORECASE)
            if m:
                entities = {k: v.strip() for k, v in m.groupdict(default="").items() if v and v.strip()}
                entities.update(self._extract_common_entities(q))
                return IntentMatch("task_update", 0.97, entities)

        # Meeting/action-item sync
        if any(x in low for x in ["capture action items", "sync action items", "import action items", "pull action items", "make tasks from meeting", "make tasks from chat"]):
            entities.update(self._extract_common_entities(q))
            return IntentMatch("task_sync", 0.96, entities)

        # Event creation/update
        for pattern in (
            r"^(?:add|create|log) event (?P<name>.+?)(?: on (?P<date>.+?))?(?: at (?P<location>.+))?$",
            r"^(?:create|add) (?P<name>[A-Za-z0-9][A-Za-z0-9 &\-']{2,50}) event(?: on (?P<date>.+?))?(?: at (?P<location>.+))?$",
        ):
            m = re.match(pattern, q, flags=re.IGNORECASE)
            if m:
                entities = {k: v.strip() for k, v in m.groupdict(default="").items() if v and v.strip()}
                entities.update(self._extract_common_entities(q))
                return IntentMatch("event_add", 0.96, entities)

        for pattern in (
            r"^(?:set|change|update) budget (?:for )?(?P<event>[A-Za-z0-9][A-Za-z0-9 &\-']{2,50}) to \$?(?P<budget>\d+(?:\.\d{1,2})?)$",
            r"^(?:set|change|update) attendance (?:for )?(?P<event>[A-Za-z0-9][A-Za-z0-9 &\-']{2,50}) to (?P<attendance>\d+)$",
            r"^(?:set|change|update) location (?:for )?(?P<event>[A-Za-z0-9][A-Za-z0-9 &\-']{2,50}) to (?P<location>.+)$",
            r"^(?:set|change|update) date (?:for )?(?P<event>[A-Za-z0-9][A-Za-z0-9 &\-']{2,50}) to (?P<date>.+)$",
            r"^(?:set|change|update) status (?:for )?(?P<event>[A-Za-z0-9][A-Za-z0-9 &\-']{2,50}) to (?P<status>[A-Za-z][A-Za-z \-]{1,20})$",
            r"^(?:set|change|update|add) notes? (?:for )?(?P<event>[A-Za-z0-9][A-Za-z0-9 &\-']{2,50}) to (?P<notes>.+)$",
        ):
            m = re.match(pattern, q, flags=re.IGNORECASE)
            if m:
                entities = {k: v.strip() for k, v in m.groupdict(default="").items() if v and v.strip()}
                entities.update(self._extract_common_entities(q))
                return IntentMatch("event_update", 0.95, entities)

        for pattern in (
            r"^(?:delete|remove) event (?P<event>[A-Za-z0-9][A-Za-z0-9 &\-']{2,50})$",
        ):
            m = re.match(pattern, q, flags=re.IGNORECASE)
            if m:
                entities = {k: v.strip() for k, v in m.groupdict(default="").items() if v and v.strip()}
                return IntentMatch("event_delete", 0.95, entities)

        if any(x in low for x in ["dashboard", "overall status", "club status", "status overview", "summary status"]):
            entities.update(self._extract_common_entities(q))
            return IntentMatch("dashboard", 0.92, entities)

        if any(x in low for x in ["meeting summary", "summarize", "summary", "meeting notes", "what happened", "last discussion"]):
            entities.update(self._extract_common_entities(q))
            return IntentMatch("meeting_summary", 0.92, entities)

        if any(x in low for x in ["upcoming", "timeline", "what's planned", "whats planned", "coming up", "calendar", "next 30"]):
            entities.update(self._extract_common_entities(q))
            return IntentMatch("timeline", 0.9, entities)

        if any(x in low for x in ["status of", "details for", "event status", "event report", "attendance for", "budget for", "who is assigned to"]):
            entities.update(self._extract_common_entities(q))
            return IntentMatch("event_status", 0.9, entities)

        if any(x in low for x in ["what should we do next", "next best step", "what do we still need", "what still needs to be done", "recommend next", "what's left", "whats left"]):
            entities.update(self._extract_common_entities(q))
            return IntentMatch("advisor", 0.95, entities)

        if any(x in low for x in ["my tasks", "open tasks", "show tasks", "all tasks", "todo", "to-do", "what am i supposed to do", "what should i do", "due this week", "high priority", "tasks for", "assigned to", "overdue tasks", "completed tasks", "done tasks", "cancelled tasks", "canceled tasks"]):
            entities.update(self._extract_common_entities(q))
            if "completed" in low or "done tasks" in low:
                entities["status"] = "done"
            elif "cancelled tasks" in low or "canceled tasks" in low:
                entities["status"] = "cancelled"
            return IntentMatch("task_query", 0.91, entities)

        if any(x in low for x in ["who was supposed to", "what did we decide", "remember when", "search memory", "look up", "who said", "find where"]):
            entities.update(self._extract_common_entities(q))
            return IntentMatch("memory_lookup", 0.87, entities)

        if low in {"help", "commands", "examples"}:
            return IntentMatch("help", 0.99, entities)

        entities.update(self._extract_common_entities(q))
        if entities.get("event"):
            return IntentMatch("event_status", 0.62, entities)
        return IntentMatch("memory_lookup", 0.46, entities)

    def _extract_common_entities(self, text: str) -> dict[str, str]:
        entities: dict[str, str] = {}
        owner = self._extract_owner_entity(text)
        event = self._extract_event_entity(text)
        due = self._extract_due_entity(text)
        priority = self._extract_priority_entity(text)
        task_id = self._extract_task_id_entity(text)
        if owner:
            entities.update(owner)
        if event:
            entities.update(event)
        if due:
            entities.update(due)
        if priority:
            entities.update(priority)
        if task_id:
            entities.update(task_id)
        return entities

    def _extract_owner_entity(self, text: str) -> dict[str, str]:
        q = normalize_spaces(text)
        for name in self._owner_hints:
            if re.search(rf"\b{name.lower()}\b", q.lower()):
                return {"owner": name}
        m = re.search(r"(?:for|assigned to|owner:?|to ) (?P<owner>[A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)?)", q)
        if m:
            return {"owner": m.group("owner")}
        return {}

    def _extract_event_entity(self, text: str) -> dict[str, str]:
        q = normalize_spaces(text)
        low = q.lower()
        for item in self._known_events:
            if item in low:
                return {"event": item}
        for pattern in (
            r"for (?P<event>[a-zA-Z0-9][a-zA-Z0-9 &\-']{2,50})$",
            r"about (?P<event>[a-zA-Z0-9][a-zA-Z0-9 &\-']{2,50})$",
            r"status of (?P<event>[a-zA-Z0-9][a-zA-Z0-9 &\-']{2,50})$",
            r"(?:budget|attendance|location|date|status) for (?P<event>[a-zA-Z0-9][a-zA-Z0-9 &\-']{2,50})",
        ):
            m = re.search(pattern, q, flags=re.IGNORECASE)
            if m:
                return {"event": m.group("event").strip()}
        return {}

    def _extract_due_entity(self, text: str) -> dict[str, str]:
        low = normalize_spaces(text).lower()
        if not low:
            return {}
        m = re.search(r"(?:by|due|on|to) (?P<due>(?:\d{4}-\d{2}-\d{2})|(?:\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)|(?:today|tomorrow|this week|next week|monday|tuesday|wednesday|thursday|friday|saturday|sunday|[a-z]{3,9} \d{1,2}(?: \d{4})?))", low)
        if m:
            return {"due": m.group("due")}
        if "due this week" in low:
            return {"due": "this week"}
        return {}

    def _extract_priority_entity(self, text: str) -> dict[str, str]:
        low = normalize_spaces(text).lower()
        for priority in ("high", "medium", "low"):
            if f"{priority} priority" in low or f"priority {priority}" in low:
                return {"priority": priority}
        if "urgent" in low:
            return {"priority": "high"}
        return {}

    def _extract_task_id_entity(self, text: str) -> dict[str, str]:
        m = re.search(r"task\s+#?(?P<task_id>\d+)", normalize_spaces(text), flags=re.IGNORECASE)
        if m:
            return {"task_id": m.group("task_id")}
        return {}
