from __future__ import annotations

from typing import Protocol

from .in_memory_state import InMemoryState


class InMemoryTransactionView(Protocol):
    state: InMemoryState
