from __future__ import annotations

from pathlib import Path
from typing import Any

from memwing_benchmark.json_utils import loads_json


def load_memwing_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = loads_json(line)
        if isinstance(event, dict):
            events.append(event)
    return events
