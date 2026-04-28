from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from memwing.api.validation import require_text


ItemT = TypeVar("ItemT")


@dataclass(frozen=True, slots=True)
class MutationEnvelope:
    actor_id: str
    reason: str
    idempotency_key: str
    trace_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "actor_id", require_text(self.actor_id, "actor_id"))
        object.__setattr__(self, "reason", require_text(self.reason, "reason"))
        object.__setattr__(
            self,
            "idempotency_key",
            require_text(self.idempotency_key, "idempotency_key"),
        )
        if self.trace_id is not None:
            object.__setattr__(self, "trace_id", require_text(self.trace_id, "trace_id"))


@dataclass(frozen=True, slots=True)
class ErrorResponse:
    code: str
    message: str
    trace_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", require_text(self.code, "code"))
        object.__setattr__(self, "message", require_text(self.message, "message"))
        if self.trace_id is not None:
            object.__setattr__(self, "trace_id", require_text(self.trace_id, "trace_id"))


@dataclass(frozen=True, slots=True)
class ListResponse:
    items: tuple[ItemT, ...]
    next_cursor: str | None
    trace_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        if self.next_cursor is not None:
            object.__setattr__(
                self,
                "next_cursor",
                require_text(self.next_cursor, "next_cursor"),
            )
        object.__setattr__(self, "trace_id", require_text(self.trace_id, "trace_id"))
