#!/usr/bin/env python3
"""
Run a small regression suite (rules-only) and write tests/latest_results.json
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

KNOWLEDGE_DIR = Path("data") / "knowledge"
CLUB_PATH = KNOWLEDGE_DIR / "club_memory.json"
CAMPUS_PATH = KNOWLEDGE_DIR / "campus_memory.json"
QA_PATH = KNOWLEDGE_DIR / "qa_rules.json"
QUESTIONS_PATH = Path("tests") / "questions.txt"

def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())

def template_fill(answer: str, club: Dict[str, Any], campus: Dict[str, Any]) -> str:
    def get(path: str) -> str:
        root, _, key = path.partition(".")
        if root == "club":
            return str(club.get(key, ""))
        if root == "campus":
            return str(campus.get(key, ""))
        return ""
    return re.sub(r"\{([a-zA-Z0-9_]+\.[a-zA-Z0-9_]+)\}", lambda m: get(m.group(1)), answer)

def match_rule(q: str, rule: Dict[str, Any]) -> bool:
    qq = norm(q)
    for key in ("match_any", "triggers", "keywords", "contains_any"):
        if isinstance(rule.get(key), list):
            for t in rule[key]:
                if isinstance(t, str) and norm(t) in qq:
                    return True
    if isinstance(rule.get("match_regex"), list):
        for pat in rule["match_regex"]:
            if isinstance(pat, str) and re.search(pat, qq, re.I):
                return True
    return False

def answer_from_rules(question: str, club: Dict[str, Any], campus: Dict[str, Any], qa: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    for r in qa.get("rules", []):
        if isinstance(r, dict) and match_rule(question, r):
            ans = r.get("answer", "")
            if isinstance(ans, str) and ans.strip():
                return template_fill(ans, club, campus), str(r.get("id", "(no id)"))
    return None

def main() -> int:
    if not QUESTIONS_PATH.exists():
        print(f"Missing {QUESTIONS_PATH}")
        return 2

    club = load_json(CLUB_PATH) if CLUB_PATH.exists() else {}
    campus = load_json(CAMPUS_PATH) if CAMPUS_PATH.exists() else {}
    qa = load_json(QA_PATH) if QA_PATH.exists() else {"rules": []}

    questions = [q.strip() for q in QUESTIONS_PATH.read_text(encoding="utf-8").splitlines() if q.strip() and not q.strip().startswith("#")]

    answered = 0
    results = {}
    for q in questions:
        hit = answer_from_rules(q, club, campus, qa)
        if hit:
            ans, rid = hit
            answered += 1
            results[q] = {"answer": ans, "rule_id": rid}
        else:
            results[q] = {"answer": None, "rule_id": None}

    coverage = 0.0 if not questions else answered / len(questions) * 100.0
    print(f"Questions: {len(questions)}  Answered by rules: {answered} ({coverage:.1f}%)")

    out = Path("tests") / "latest_results.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Saved: {out}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
