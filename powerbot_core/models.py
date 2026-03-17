from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class HubResult:
    text: str
    intent: str
    metadata: dict[str, Any] = field(default_factory=dict)
