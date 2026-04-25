from __future__ import annotations

from typing import Protocol


class ChatModelClient(Protocol):
    def complete_json(self, *, system: str, user: str, temperature: float = 0.0) -> dict: ...
