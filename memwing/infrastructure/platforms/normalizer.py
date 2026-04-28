from __future__ import annotations

import json
from datetime import UTC, datetime

from memwing.api.platform import (
    PlatformEvent,
    PlatformRawEvent,
    PlatformRawRequest,
    PlatformRef,
    PlatformSourceType,
)
from memwing.api.types import JsonObject, JsonValue
from memwing.api.validation import SchemaValidationError, require_text


def build_feishu_raw_event(
    raw_request: PlatformRawRequest,
    event_payload: JsonObject,
) -> PlatformRawEvent:
    if raw_request.platform != "feishu":
        raise SchemaValidationError("raw_request platform must be feishu")

    header = _object_field(event_payload, "header")
    event = _event_body(event_payload)
    message = _object_field(event, "message")
    chat_id = _first_text(
        message.get("chat_id"),
        event.get("chat_id"),
        event.get("open_chat_id"),
        event.get("group_id"),
    )
    if chat_id is None:
        raise SchemaValidationError("chat_id is required")

    message_id = _first_text(
        message.get("message_id"),
        event.get("message_id"),
        header.get("event_id"),
    )
    thread_id = _first_text(
        message.get("root_id"),
        message.get("parent_id"),
        event.get("root_id"),
        event.get("thread_id"),
    )
    tenant_id = _first_text(
        header.get("tenant_key"),
        event.get("tenant_key"),
        _object_field(event.get("sender"), "sender_id").get("tenant_key"),
    )

    return PlatformRawEvent(
        platform_ref=PlatformRef(
            platform="feishu",
            tenant_id=tenant_id,
            channel_id=chat_id,
            thread_id=thread_id,
            message_id=message_id,
        ),
        raw_request=raw_request,
        event_payload=event_payload,
        is_challenge=False,
    )


def normalize_feishu_event(
    raw_event: PlatformRawEvent,
    *,
    project_memory_space_id: str,
) -> PlatformEvent:
    if raw_event.platform_ref.platform != "feishu":
        raise SchemaValidationError("platform_ref platform must be feishu")
    if raw_event.is_challenge:
        raise SchemaValidationError("challenge payload cannot be normalized")

    project_id = require_text(project_memory_space_id, "project_memory_space_id")
    payload = raw_event.event_payload
    header = _object_field(payload, "header")
    event = _event_body(payload)
    message = _object_field(event, "message")

    message_type = _first_text(
        message.get("message_type"),
        message.get("msg_type"),
        event.get("message_type"),
        event.get("msg_type"),
    )
    event_type = _first_text(header.get("event_type"), payload.get("type"), event.get("type"))
    source_type = _source_type_from_feishu_type(message_type, event_type)
    content_data = _content_data(message.get("content", event.get("content")))
    content = _extract_content(source_type, content_data, message, event)
    source_url = _source_url(content_data, message, event)

    chat_id = require_text(raw_event.platform_ref.channel_id, "chat_id")
    thread_id = raw_event.platform_ref.thread_id
    author = _object_field(event.get("sender"), "sender_id")
    sender = _object_field(event.get("sender"))
    author_id = _first_text(author.get("open_id"), author.get("user_id"), author.get("union_id"))
    author_name = _first_text(
        sender.get("sender_name"),
        sender.get("name"),
        _object_field(sender.get("sender_name")).get("name"),
    )
    event_time = (
        _parse_feishu_time(message.get("create_time"))
        or _parse_feishu_time(event.get("create_time"))
        or _parse_feishu_time(header.get("create_time"))
        or raw_event.raw_request.received_at
    )

    return PlatformEvent(
        platform_ref=PlatformRef(
            platform="feishu",
            tenant_id=raw_event.platform_ref.tenant_id,
            channel_id=chat_id,
            thread_id=thread_id,
            message_id=raw_event.platform_ref.message_id,
        ),
        project_memory_space_id=project_id,
        group_id=chat_id,
        thread_id=thread_id,
        shared_group_id=None,
        author_id=author_id,
        author_name=author_name,
        source_type=source_type,
        content=content,
        source_url=source_url,
        event_time=event_time,
        raw_payload=payload,
    )


def _event_body(payload: JsonObject) -> JsonObject:
    event = _object_field(payload, "event")
    if event:
        return event
    return payload


def _object_field(value: object, field_name: str | None = None) -> JsonObject:
    if field_name is not None and isinstance(value, dict):
        field_value = value.get(field_name)
    else:
        field_value = value
    if not isinstance(field_value, dict):
        return {}
    return _to_json_object(field_value)


def _to_json_object(mapping: dict[object, object]) -> JsonObject:
    return {str(key): _to_json_value(value) for key, value in mapping.items()}


def _to_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list | tuple):
        return tuple(_to_json_value(item) for item in value)
    if isinstance(value, dict):
        return {str(key): _to_json_value(item) for key, item in value.items()}
    return str(value)


def _content_data(value: JsonValue | object) -> JsonObject | str | None:
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return stripped
        if isinstance(parsed, dict):
            return _to_json_object(parsed)
        if isinstance(parsed, str):
            return parsed
        return str(parsed)
    if isinstance(value, dict):
        return _to_json_object(value)
    return None


def _source_type_from_feishu_type(
    message_type: str | None,
    event_type: str | None,
) -> PlatformSourceType:
    combined = f"{message_type or ''} {event_type or ''}".lower()
    if "post" in combined:
        return "post"
    if "doc" in combined or "wiki" in combined:
        return "doc"
    if "task" in combined or "todo" in combined:
        return "task"
    if "calendar" in combined:
        return "calendar"
    if "file" in combined or "folder" in combined:
        return "file"
    return "text"


def _extract_content(
    source_type: PlatformSourceType,
    content_data: JsonObject | str | None,
    message: JsonObject,
    event: JsonObject,
) -> str:
    if isinstance(content_data, str):
        content = content_data
    elif source_type == "text":
        content = _first_text(
            _field(content_data, "text"),
            message.get("text"),
            event.get("text"),
        )
    elif source_type == "file":
        file_name = _first_text(
            _field(content_data, "file_name"),
            _field(content_data, "name"),
            message.get("file_name"),
            event.get("file_name"),
        )
        file_key = _first_text(_field(content_data, "file_key"), event.get("file_key"))
        file_parts = [part for part in (file_name, file_key) if part]
        content = f"File: {' '.join(file_parts)}" if file_parts else ""
    else:
        content = " ".join(_flatten_text(content_data))

    if not isinstance(content, str) or not content.strip():
        content = " ".join(_flatten_text(message)) or " ".join(_flatten_text(event))
    return require_text(content, "content")


def _source_url(
    content_data: JsonObject | str | None,
    message: JsonObject,
    event: JsonObject,
) -> str | None:
    if isinstance(content_data, dict):
        url = _first_text(
            content_data.get("url"),
            content_data.get("source_url"),
            content_data.get("doc_url"),
            content_data.get("file_url"),
        )
        if url is not None:
            return url
    return _first_text(
        message.get("url"),
        message.get("source_url"),
        event.get("url"),
        event.get("source_url"),
    )


def _field(mapping: JsonObject | str | None, key: str) -> object:
    if isinstance(mapping, dict):
        return mapping.get(key)
    return None


def _flatten_text(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        stripped = value.strip()
        return (stripped,) if stripped else ()
    if isinstance(value, bool | int | float):
        return (str(value),)
    if isinstance(value, list | tuple):
        parts: list[str] = []
        for item in value:
            parts.extend(_flatten_text(item))
        return tuple(parts)
    if isinstance(value, dict):
        parts = []
        for key in (
            "title",
            "text",
            "content",
            "name",
            "file_name",
            "summary",
            "description",
            "url",
        ):
            if key in value:
                parts.extend(_flatten_text(value[key]))
        return tuple(parts)
    return ()


def _parse_feishu_time(value: object) -> datetime | None:
    text = _first_text(value)
    if text is None:
        return None
    try:
        timestamp = int(text)
    except ValueError:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if timestamp > 10_000_000_000:
        return datetime.fromtimestamp(timestamp / 1000, tz=UTC)
    return datetime.fromtimestamp(timestamp, tz=UTC)


def _first_text(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, int | float) and not isinstance(value, bool):
            return str(value)
    return None
