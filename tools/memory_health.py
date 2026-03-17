#!/usr/bin/env python3
"""
Check archive sizes and suggest pruning/migration thresholds.
"""
from __future__ import annotations

import json
from pathlib import Path

KNOWLEDGE_DIR = Path("data") / "knowledge"
GENCHAT = KNOWLEDGE_DIR / "gen_chat_archive.json"
COMPILED = KNOWLEDGE_DIR / "compiled_rules.json"

def mb(path: Path) -> float:
    return path.stat().st_size / (1024 * 1024)

def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def main() -> int:
    print("PowerBot Memory Health\n")
    if GENCHAT.exists():
        size = mb(GENCHAT)
        data = load_json(GENCHAT)
        msgs = data.get("messages", [])
        n = len(msgs) if isinstance(msgs, list) else 0
        print(f"- gen_chat_archive.json: {size:.2f} MB, messages: {n}")
        if size > 25:
            print("  ⚠️ Consider pruning or migrating to SQLite.")
    else:
        print("- gen_chat_archive.json: (missing)")

    if COMPILED.exists():
        print(f"- compiled_rules.json: {mb(COMPILED):.2f} MB")
    else:
        print("- compiled_rules.json: (missing)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
