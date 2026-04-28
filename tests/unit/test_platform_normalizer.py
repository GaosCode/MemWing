from datetime import UTC, datetime

import pytest

from memwing.api.platform import PlatformRawRequest
from memwing.api.validation import SchemaValidationError
from memwing.infrastructure.platforms.normalizer import (
    build_feishu_raw_event,
    normalize_feishu_event,
)


RECEIVED_AT = datetime(2026, 4, 28, 12, 0, tzinfo=UTC)


def test_feishu_text_message_maps_chat_and_root_thread_to_platform_event() -> None:
    raw_event = build_feishu_raw_event(
        _raw_request(),
        {
            "schema": "2.0",
            "header": {
                "event_id": "event_001",
                "event_type": "im.message.receive_v1",
                "tenant_key": "tenant_001",
            },
            "event": {
                "sender": {
                    "sender_id": {"open_id": "ou_001"},
                    "sender_name": "Ada",
                },
                "message": {
                    "message_id": "om_001",
                    "root_id": "om_root",
                    "chat_id": "oc_group_001",
                    "message_type": "text",
                    "content": '{"text":"Ship the Feishu skeleton."}',
                    "create_time": str(int(RECEIVED_AT.timestamp() * 1000)),
                },
            },
        },
    )

    event = normalize_feishu_event(raw_event, project_memory_space_id="project_001")

    assert event.platform_ref.tenant_id == "tenant_001"
    assert event.group_id == "oc_group_001"
    assert event.thread_id == "om_root"
    assert event.author_id == "ou_001"
    assert event.author_name == "Ada"
    assert event.source_type == "text"
    assert event.content == "Ship the Feishu skeleton."
    assert event.event_time == RECEIVED_AT


@pytest.mark.parametrize(
    ("message_type", "content", "expected_type", "expected_text"),
    (
        (
            "post",
            '{"title":"Plan","content":[[{"tag":"text","text":"Review C1"}]]}',
            "post",
            "Plan Review C1",
        ),
        ("doc", '{"title":"Spec","url":"https://example.test/spec"}', "doc", "Spec https://example.test/spec"),
        ("todo", '{"summary":"Close task C1"}', "task", "Close task C1"),
        ("calendar", '{"summary":"Design review"}', "calendar", "Design review"),
        ("file", '{"file_name":"notes.md","file_key":"file_001"}', "file", "File: notes.md file_001"),
    ),
)
def test_feishu_supported_message_types_normalize_content(
    message_type: str,
    content: str,
    expected_type: str,
    expected_text: str,
) -> None:
    raw_event = build_feishu_raw_event(
        _raw_request(),
        {
            "header": {"tenant_key": "tenant_001"},
            "event": {
                "message": {
                    "message_id": "om_001",
                    "chat_id": "oc_group_001",
                    "message_type": message_type,
                    "content": content,
                }
            },
        },
    )

    event = normalize_feishu_event(raw_event, project_memory_space_id="project_001")

    assert event.source_type == expected_type
    assert event.content == expected_text


def test_feishu_event_requires_chat_id_as_group_id_source() -> None:
    with pytest.raises(SchemaValidationError, match="chat_id"):
        build_feishu_raw_event(
            _raw_request(),
            {"event": {"message": {"message_id": "om_001", "content": '{"text":"No chat"}'}}},
        )


def _raw_request() -> PlatformRawRequest:
    return PlatformRawRequest(
        platform="feishu",
        headers={"x-lark-request-timestamp": "1777377600"},
        body=b'{"event":{}}',
        received_at=RECEIVED_AT,
        raw_payload_hash="hash_001",
    )
