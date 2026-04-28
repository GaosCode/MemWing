from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from memwing.api.types import JsonObject
from memwing.api.validation import SchemaValidationError, require_text


PlatformName = Literal["feishu", "slack", "future_platform"]
PlatformSourceType = Literal["text", "post", "doc", "task", "base", "calendar", "file"]


@dataclass(frozen=True, slots=True)
class PlatformRawRequest:
    platform: PlatformName
    headers: dict[str, str]
    body: bytes
    received_at: datetime
    raw_payload_hash: str

    def __post_init__(self) -> None:
        if self.platform not in ("feishu", "slack", "future_platform"):
            raise SchemaValidationError("platform is not supported")
        object.__setattr__(
            self,
            "headers",
            {
                require_text(key, "headers"): require_text(value, "headers")
                for key, value in self.headers.items()
            },
        )
        if not isinstance(self.body, bytes) or not self.body:
            raise SchemaValidationError("body is required")
        object.__setattr__(
            self,
            "raw_payload_hash",
            require_text(self.raw_payload_hash, "raw_payload_hash"),
        )


@dataclass(frozen=True, slots=True)
class PlatformRef:
    platform: PlatformName
    tenant_id: str | None
    channel_id: str
    thread_id: str | None
    message_id: str | None

    def __post_init__(self) -> None:
        if self.platform not in ("feishu", "slack", "future_platform"):
            raise SchemaValidationError("platform is not supported")
        object.__setattr__(self, "channel_id", require_text(self.channel_id, "channel_id"))
        if self.tenant_id is not None:
            object.__setattr__(self, "tenant_id", require_text(self.tenant_id, "tenant_id"))
        if self.thread_id is not None:
            object.__setattr__(self, "thread_id", require_text(self.thread_id, "thread_id"))
        if self.message_id is not None:
            object.__setattr__(self, "message_id", require_text(self.message_id, "message_id"))


@dataclass(frozen=True, slots=True)
class PlatformRawEvent:
    platform_ref: PlatformRef
    raw_request: PlatformRawRequest
    event_payload: JsonObject
    is_challenge: bool


@dataclass(frozen=True, slots=True)
class PlatformEvent:
    platform_ref: PlatformRef
    project_memory_space_id: str
    group_id: str
    thread_id: str | None
    shared_group_id: str | None
    author_id: str | None
    author_name: str | None
    source_type: PlatformSourceType
    content: str
    source_url: str | None
    event_time: datetime
    raw_payload: JsonObject

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "project_memory_space_id",
            require_text(self.project_memory_space_id, "project_memory_space_id"),
        )
        object.__setattr__(self, "group_id", require_text(self.group_id, "group_id"))
        if self.thread_id is not None:
            object.__setattr__(self, "thread_id", require_text(self.thread_id, "thread_id"))
        if self.shared_group_id is not None:
            object.__setattr__(
                self,
                "shared_group_id",
                require_text(self.shared_group_id, "shared_group_id"),
            )
        if self.author_id is not None:
            object.__setattr__(self, "author_id", require_text(self.author_id, "author_id"))
        if self.author_name is not None:
            object.__setattr__(self, "author_name", require_text(self.author_name, "author_name"))
        if self.source_type not in ("text", "post", "doc", "task", "base", "calendar", "file"):
            raise SchemaValidationError("source_type is not supported")
        object.__setattr__(self, "content", require_text(self.content, "content"))
        if self.source_url is not None:
            object.__setattr__(self, "source_url", require_text(self.source_url, "source_url"))


@dataclass(frozen=True, slots=True)
class PushCandidate:
    id: str
    platform_ref: PlatformRef
    content: str
    trace_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", require_text(self.id, "id"))
        object.__setattr__(self, "content", require_text(self.content, "content"))
        object.__setattr__(self, "trace_id", require_text(self.trace_id, "trace_id"))


@dataclass(frozen=True, slots=True)
class PlatformSendResult:
    candidate_id: str
    delivered: bool
    trace_id: str
    provider_message_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_id",
            require_text(self.candidate_id, "candidate_id"),
        )
        object.__setattr__(self, "trace_id", require_text(self.trace_id, "trace_id"))
        if self.provider_message_id is not None:
            object.__setattr__(
                self,
                "provider_message_id",
                require_text(self.provider_message_id, "provider_message_id"),
            )
