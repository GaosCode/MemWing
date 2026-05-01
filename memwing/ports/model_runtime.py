from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


MemWingModelRole = Literal[
    "page_memory",
    "long_term_filter",
    "graphiti_extraction",
    "graphiti_embedding",
    "graphiti_rerank",
]
MemWingModelRuntime = Literal["test", "openai_compatible", "openclaw"]
MemWingModelTransport = Literal["local", "gateway"]

MEMWING_MODEL_ROLES: tuple[MemWingModelRole, ...] = (
    "page_memory",
    "long_term_filter",
    "graphiti_extraction",
    "graphiti_embedding",
    "graphiti_rerank",
)


@dataclass(frozen=True, slots=True)
class MemWingModelSelection:
    role: MemWingModelRole
    runtime: MemWingModelRuntime
    model: str | None
    transport: MemWingModelTransport | None
    timeout_seconds: float


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


@runtime_checkable
class EmbeddingModelClient(Protocol):
    async def embed(self, input: str) -> tuple[float, ...]:
        ...

    async def embed_batch(self, inputs: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        ...
