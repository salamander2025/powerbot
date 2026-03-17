"""Optional dependency detection.

PowerBot can run with minimal deps. These helpers let commands show what is available.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass


@dataclass(frozen=True)
class OptionalDeps:
    faiss: bool
    sentence_transformers: bool
    apscheduler: bool
    pandas: bool
    prophet: bool
    loguru: bool
    cerberus: bool


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def detect() -> OptionalDeps:
    return OptionalDeps(
        faiss=has_module("faiss") or has_module("faiss_cpu") or has_module("faiss.contrib"),
        sentence_transformers=has_module("sentence_transformers"),
        apscheduler=has_module("apscheduler"),
        pandas=has_module("pandas"),
        prophet=has_module("prophet"),
        loguru=has_module("loguru"),
        cerberus=has_module("cerberus"),
    )
