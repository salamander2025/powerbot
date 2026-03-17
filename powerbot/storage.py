"""Safe storage helpers (JSON + atomic writes).

Centralizes file I/O so the bot doesn't corrupt JSON on crashes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _clone_default(default: Any) -> Any:
    if isinstance(default, dict):
        return dict(default)
    if isinstance(default, list):
        return list(default)
    return default


def read_json(path: str, default: Any) -> Any:
    """Read JSON from `path`. If missing/corrupt, returns a copy of `default`."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception:
        return _clone_default(default)


def write_json(path: str, data: Any, *, indent: int = 2) -> None:
    """Write JSON atomically (write temp then os.replace). Never raises."""
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception:
        # Best-effort cleanup
        try:
            tmp_path = f"{path}.tmp"
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def append_json_list(path: str, item: Any, *, schema: str | None = None) -> None:
    """Append `item` into a JSON file.

    Supports two formats:
    - A raw list JSON file (events.json style)
    - A dict with a `messages` list (archive style)
    """
    try:
        existing = read_json(path, [] if schema is None else {"schema": schema, "messages": []})
        if isinstance(existing, list):
            existing.append(item)
            write_json(path, existing)
            return
        if isinstance(existing, dict):
            key = "messages" if "messages" in existing else "items"
            if key not in existing or not isinstance(existing.get(key), list):
                existing[key] = []
            existing[key].append(item)
            if schema and "schema" not in existing:
                existing["schema"] = schema
            write_json(path, existing)
            return
        # Unknown format -> overwrite with list
        write_json(path, [item])
    except Exception:
        return
