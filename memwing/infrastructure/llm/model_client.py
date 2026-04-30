from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class LLMModelRequest:
    system_prompt: str
    user_prompt: str
    trace_id: str | None


@dataclass(frozen=True, slots=True)
class LLMModelResponse:
    text: str
    provider: str
    model: str


@runtime_checkable
class LLMModelClient(Protocol):
    async def complete(self, request: LLMModelRequest) -> LLMModelResponse:
        ...
