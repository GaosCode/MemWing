import asyncio
import json
from datetime import UTC, datetime

from memwing.api.agent_runtime import RememberEventResult
from memwing.api.platform import PlatformEvent
from memwing.api.platform_webhooks import handle_feishu_webhook
from memwing.infrastructure.platforms.feishu_connector import (
    FeishuConnector,
    compute_feishu_signature,
)


RECEIVED_AT = datetime(2026, 4, 28, 12, 0, tzinfo=UTC)
SECRET = "secret_001"


def test_feishu_webhook_routes_platform_event_to_remember_client() -> None:
    remember_client = FakeRememberClient()
    body = json.dumps(_message_payload()).encode()
    connector = FeishuConnector(project_memory_space_id="project_001", signing_secret=SECRET)

    response = asyncio.run(
        handle_feishu_webhook(
            headers=_signed_headers(body),
            body=body,
            connector=connector,
            remember_client=remember_client,
            received_at=RECEIVED_AT,
        )
    )

    assert response.status_code == 202
    assert response.body["remembered"] is True
    assert response.body["source_event_id"] == "source_001"
    assert len(remember_client.events) == 1
    assert remember_client.events[0].group_id == "oc_group_001"
    assert remember_client.events[0].thread_id == "om_root"
    assert remember_client.events[0].content == "Remember this Feishu message."


def _message_payload() -> dict[str, object]:
    return {
        "schema": "2.0",
        "header": {
            "event_id": "event_001",
            "event_type": "im.message.receive_v1",
            "tenant_key": "tenant_001",
        },
        "event": {
            "sender": {"sender_id": {"open_id": "ou_001"}, "sender_name": "Ada"},
            "message": {
                "message_id": "om_001",
                "root_id": "om_root",
                "chat_id": "oc_group_001",
                "message_type": "text",
                "content": '{"text":"Remember this Feishu message."}',
                "create_time": str(int(RECEIVED_AT.timestamp() * 1000)),
            },
        },
    }


def _signed_headers(body: bytes) -> dict[str, str]:
    timestamp = str(int(RECEIVED_AT.timestamp()))
    nonce = "nonce_001"
    return {
        "X-Lark-Request-Timestamp": timestamp,
        "X-Lark-Request-Nonce": nonce,
        "X-Lark-Signature": compute_feishu_signature(
            signing_secret=SECRET,
            timestamp=timestamp,
            nonce=nonce,
            body=body,
        ),
    }


class FakeRememberClient:
    def __init__(self) -> None:
        self.events: list[PlatformEvent] = []

    async def remember_event(self, event: PlatformEvent) -> RememberEventResult:
        self.events.append(event)
        return RememberEventResult(
            source_event_id="source_001",
            accepted=True,
            trace_id="trace_001",
        )
