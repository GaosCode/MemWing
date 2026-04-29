import asyncio
import json
from datetime import UTC, datetime

from memwing.api.agent_runtime import RememberEventResult
from memwing.api.platform_webhooks import handle_feishu_webhook
from memwing.application.remember_event_command import RememberEventCommand
from memwing.infrastructure.platforms.feishu_connector import (
    FeishuConnector,
    compute_feishu_signature,
)


RECEIVED_AT = datetime(2026, 4, 28, 12, 0, tzinfo=UTC)
SECRET = "secret_001"


def test_feishu_webhook_routes_raw_event_to_remember_command() -> None:
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
    assert len(remember_client.commands) == 1
    command = remember_client.commands[0]
    assert command.source_ref.kind == "platform"
    assert command.scope_hint.group_id == "oc_group_001"
    assert command.scope_hint.thread_id == "om_root"
    assert command.content == "Remember this Feishu message."


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
        self.commands: list[RememberEventCommand] = []

    async def remember_event(self, command: RememberEventCommand) -> RememberEventResult:
        self.commands.append(command)
        return RememberEventResult(
            source_event_id="source_001",
            accepted=True,
            trace_id="trace_001",
        )
