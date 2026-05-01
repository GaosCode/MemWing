from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from memwing.core.platform import PlatformEvent, PlatformRef
from memwing.core.runtime import AgentRuntimeEvent, AgentRuntimeRef
from memwing.core.scope import MemoryScope
from memwing.core.types import JsonObject, JsonValue
from memwing.core.validation import SchemaValidationError, require_text


SourceRefKind = Literal["platform", "agent_runtime"]


@dataclass(frozen=True, slots=True)
class ActorRef:
    id: str | None
    name: str | None

    def __post_init__(self) -> None:
        if self.id is not None:
            object.__setattr__(self, "id", require_text(self.id, "author.id"))
        if self.name is not None:
            object.__setattr__(self, "name", require_text(self.name, "author.name"))


@dataclass(frozen=True, slots=True)
class SourceRef:
    kind: SourceRefKind
    platform_ref: PlatformRef | None = None
    runtime_ref: AgentRuntimeRef | None = None
    run_id: str | None = None
    message_id: str | None = None
    tool_call_id: str | None = None
    hook_name: str | None = None
    event_type: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("platform", "agent_runtime"):
            raise SchemaValidationError("source_ref.kind is not supported")
        if self.kind == "platform" and self.platform_ref is None:
            raise SchemaValidationError("source_ref.platform_ref is required")
        if self.kind == "agent_runtime" and self.runtime_ref is None:
            raise SchemaValidationError("source_ref.runtime_ref is required")
        for field_name in ("run_id", "message_id", "tool_call_id", "hook_name", "event_type"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, require_text(value, f"source_ref.{field_name}"))

    def to_metadata(self) -> JsonObject:
        if self.kind == "platform":
            if self.platform_ref is None:
                raise SchemaValidationError("source_ref.platform_ref is required")
            return {
                "kind": "platform",
                "platform": self.platform_ref.platform,
                "tenant_id": self.platform_ref.tenant_id,
                "channel_id": self.platform_ref.channel_id,
                "thread_id": self.platform_ref.thread_id,
                "message_id": self.platform_ref.message_id,
            }
        if self.runtime_ref is None:
            raise SchemaValidationError("source_ref.runtime_ref is required")
        return {
            "kind": "agent_runtime",
            "runtime": self.runtime_ref.runtime,
            "agent_id": self.runtime_ref.agent_id,
            "workspace_id": self.runtime_ref.workspace_id,
            "session_id": self.runtime_ref.session_id,
            "run_id": self.run_id,
            "message_id": self.message_id,
            "tool_call_id": self.tool_call_id,
            "hook_name": self.hook_name,
            "event_type": self.event_type,
        }


@dataclass(frozen=True, slots=True)
class RememberEventCommand:
    source_ref: SourceRef
    scope_hint: MemoryScope
    author: ActorRef
    source_type: str
    content: str
    source_url: str | None
    event_time: datetime
    idempotency_key: str | None
    payload_for_dedupe_hash: JsonValue | bytes
    adapter_metadata: JsonObject

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_type", require_text(self.source_type, "source_type"))
        object.__setattr__(self, "content", require_text(self.content, "content"))
        if self.source_url is not None:
            object.__setattr__(self, "source_url", require_text(self.source_url, "source_url"))
        if self.idempotency_key is not None:
            object.__setattr__(
                self,
                "idempotency_key",
                require_text(self.idempotency_key, "idempotency_key"),
            )
        if not isinstance(self.adapter_metadata, Mapping):
            raise SchemaValidationError("adapter_metadata must be an object")


def platform_event_to_remember_command(event: PlatformEvent) -> RememberEventCommand:
    return RememberEventCommand(
        source_ref=SourceRef(kind="platform", platform_ref=event.platform_ref),
        scope_hint=MemoryScope(
            project_memory_space_id=event.project_memory_space_id,
            group_id=event.group_id,
            thread_id=event.thread_id,
            shared_group_id=event.shared_group_id,
        ),
        author=ActorRef(id=event.author_id, name=event.author_name),
        source_type=event.source_type,
        content=event.content,
        source_url=event.source_url,
        event_time=event.event_time,
        idempotency_key=None,
        payload_for_dedupe_hash=event.raw_payload,
        adapter_metadata={"raw_payload": event.raw_payload},
    )


def agent_runtime_event_to_remember_command(event: AgentRuntimeEvent) -> RememberEventCommand:
    payload_for_dedupe_hash: JsonObject = {
        "runtime": event.runtime_ref.runtime,
        "agent_id": event.runtime_ref.agent_id,
        "workspace_id": event.runtime_ref.workspace_id,
        "session_id": event.runtime_ref.session_id,
        "run_id": event.run_id,
        "message_id": event.message_id,
        "tool_call_id": event.tool_call_id,
        "hook_name": event.hook_name,
        "sequence": event.sequence,
        "idempotency_key": event.idempotency_key,
        "event_type": event.event_type,
        "content": event.content,
        "payload": event.payload,
        "event_time": event.event_time.isoformat(),
    }
    return RememberEventCommand(
        source_ref=SourceRef(
            kind="agent_runtime",
            runtime_ref=event.runtime_ref,
            run_id=event.run_id,
            message_id=event.message_id,
            tool_call_id=event.tool_call_id,
            hook_name=event.hook_name,
            event_type=event.event_type,
        ),
        scope_hint=event.scope,
        author=ActorRef(id=None, name=None),
        source_type=f"agent_runtime.{event.event_type}",
        content=event.content or "",
        source_url=None,
        event_time=event.event_time,
        idempotency_key=event.idempotency_key,
        payload_for_dedupe_hash=payload_for_dedupe_hash,
        adapter_metadata={"payload": event.payload},
    )
