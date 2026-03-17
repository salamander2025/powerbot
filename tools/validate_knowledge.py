#!/usr/bin/env python3
"""
PowerBot Knowledge Validator
Exit 0 if OK; exit 1 if errors.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Tuple

DEFAULT_KNOWLEDGE_DIR = Path("data") / "knowledge"
FILES = {
    "club": DEFAULT_KNOWLEDGE_DIR / "club_memory.json",
    "campus": DEFAULT_KNOWLEDGE_DIR / "campus_memory.json",
    "qa": DEFAULT_KNOWLEDGE_DIR / "qa_rules.json",
    "genchat": DEFAULT_KNOWLEDGE_DIR / "gen_chat_archive.json",
    "compiled": DEFAULT_KNOWLEDGE_DIR / "compiled_rules.json",
    "schedules": DEFAULT_KNOWLEDGE_DIR / "schedules.json",
    "planning_notes": DEFAULT_KNOWLEDGE_DIR / "planning_notes.json",
}

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]?\d{3}[-.\s]?\d{4}\b")

@dataclass
class Issue:
    level: str
    file: str
    message: str

def load_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    if not path.exists():
        return None, f"missing file: {path}"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as e:
        return None, f"invalid JSON: {e}"

def is_nonempty_str(x: Any) -> bool:
    return isinstance(x, str) and x.strip() != ""

def ensure_list_of_str(x: Any) -> bool:
    return isinstance(x, list) and all(isinstance(i, str) and i.strip() for i in x)

def check_club_memory(obj: Any, file_label: str) -> List[Issue]:
    issues: List[Issue] = []
    if not isinstance(obj, dict):
        return [Issue("ERROR", file_label, "club_memory.json must be a JSON object (dict).")]

    required_any = {
        "meeting_day": ["meeting_day", "meetingDay", "meeting.day"],
        "meeting_time": ["meeting_time", "meetingTime", "meeting.time"],
    }
    for logical, candidates in required_any.items():
        if not any(k in obj and is_nonempty_str(obj.get(k)) for k in candidates):
            issues.append(Issue("ERROR", file_label, f"Missing required field: {logical} (one of {candidates})."))

    for logical, candidates in {
        "meeting_room": ["meeting_room", "meetingRoom", "meeting.room"],
        "club_name": ["club_name", "clubName", "name"],
    }.items():
        if not any(k in obj and is_nonempty_str(obj.get(k)) for k in candidates):
            issues.append(Issue("WARN", file_label, f"Recommended field not found: {logical} (one of {candidates})."))

    return issues

def check_campus_memory(obj: Any, file_label: str) -> List[Issue]:
    issues: List[Issue] = []
    if not isinstance(obj, dict):
        return [Issue("ERROR", file_label, "campus_memory.json must be a JSON object (dict).")]
    if len(obj) == 0:
        issues.append(Issue("ERROR", file_label, "campus_memory.json is empty."))

    buildings = obj.get("buildings") or obj.get("campus_buildings") or obj.get("campus")
    if buildings is None:
        issues.append(Issue("WARN", file_label, "No 'buildings' section found (recommended)."))
    conduct = obj.get("code_of_conduct") or obj.get("conduct") or obj.get("student_code_of_conduct")
    if conduct is None:
        issues.append(Issue("WARN", file_label, "No 'code_of_conduct' section found (recommended)."))
    return issues

def check_qa_rules(obj: Any, file_label: str) -> List[Issue]:
    issues: List[Issue] = []
    if not isinstance(obj, dict):
        return [Issue("ERROR", file_label, "qa_rules.json must be a JSON object (dict).")]

    rules = obj.get("rules")
    if rules is None:
        return [Issue("ERROR", file_label, "qa_rules.json missing top-level 'rules' array.")]
    if not isinstance(rules, list):
        return [Issue("ERROR", file_label, "'rules' must be an array.")]

    seen_ids = set()
    for idx, r in enumerate(rules):
        where = f"rules[{idx}]"
        if not isinstance(r, dict):
            issues.append(Issue("ERROR", file_label, f"{where} must be an object."))
            continue

        rid = r.get("id")
        if is_nonempty_str(rid):
            if rid in seen_ids:
                issues.append(Issue("ERROR", file_label, f"{where} duplicate id '{rid}'."))
            seen_ids.add(rid)

        triggers_ok = False
        for key in ("match_any", "triggers", "keywords", "contains_any"):
            if key in r:
                if ensure_list_of_str(r.get(key)):
                    triggers_ok = True
                else:
                    issues.append(Issue("ERROR", file_label, f"{where} '{key}' must be a non-empty list of strings."))

        if "match_regex" in r:
            mr = r.get("match_regex")
            if isinstance(mr, list) and all(is_nonempty_str(x) for x in mr):
                triggers_ok = True
                for pat in mr:
                    try:
                        re.compile(pat, re.I)
                    except Exception as e:
                        issues.append(Issue("ERROR", file_label, f"{where} invalid regex '{pat}': {e}"))
            else:
                issues.append(Issue("ERROR", file_label, f"{where} 'match_regex' must be a list of regex strings."))

        if not triggers_ok:
            issues.append(Issue("ERROR", file_label, f"{where} has no valid triggers."))

        ans = r.get("answer")
        if not is_nonempty_str(ans):
            issues.append(Issue("ERROR", file_label, f"{where} missing non-empty 'answer'."))

        if isinstance(ans, str) and (EMAIL_RE.search(ans) or PHONE_RE.search(ans)):
            issues.append(Issue("WARN", file_label, f"{where} answer contains email/phone-like text (consider redaction)."))

    return issues

def check_gen_chat(obj: Any, file_label: str) -> List[Issue]:
    issues: List[Issue] = []
    if obj is None:
        return issues
    if not isinstance(obj, dict):
        return [Issue("ERROR", file_label, "gen_chat_archive.json must be a JSON object (dict).")]
    msgs = obj.get("messages")
    if msgs is None:
        issues.append(Issue("WARN", file_label, "No 'messages' array found (expected)."))
        return issues
    if not isinstance(msgs, list):
        return [Issue("ERROR", file_label, "'messages' must be an array.")]
    return issues

def main() -> int:
    all_issues: List[Issue] = []

    club, err = load_json(FILES["club"])
    if err:
        all_issues.append(Issue("ERROR", "club_memory.json", err))
    else:
        all_issues.extend(check_club_memory(club, "club_memory.json"))

    campus, err = load_json(FILES["campus"])
    if err:
        all_issues.append(Issue("WARN", "campus_memory.json", err))
    else:
        all_issues.extend(check_campus_memory(campus, "campus_memory.json"))

    qa, err = load_json(FILES["qa"])
    if err:
        all_issues.append(Issue("ERROR", "qa_rules.json", err))
    else:
        all_issues.extend(check_qa_rules(qa, "qa_rules.json"))

    gen, err = load_json(FILES["genchat"])
    if err:
        all_issues.append(Issue("WARN", "gen_chat_archive.json", err))
    else:
        all_issues.extend(check_gen_chat(gen, "gen_chat_archive.json"))

    comp, err = load_json(FILES["compiled"])
    if err:
        all_issues.append(Issue("WARN", "compiled_rules.json", err))

    errors = [i for i in all_issues if i.level == "ERROR"]
    warns = [i for i in all_issues if i.level == "WARN"]

    for i in errors + warns:
        print(f"[{i.level}] {i.file}: {i.message}")

    print(f"\nSummary: Errors={len(errors)}  Warnings={len(warns)}")
    if errors:
        print("Fix errors before deploying.")
        return 1
    print("Knowledge files look good.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
