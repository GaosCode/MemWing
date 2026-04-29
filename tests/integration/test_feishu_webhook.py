import asyncio
import json
from datetime import UTC, datetime

from memwing.api.platform_webhooks import handle_feishu_webhook
from memwing.application.gateway_service import MemoryGateway
from memwing.application.platform_ingress_service import PlatformIngressService
from memwing.application.scope_resolver import ScopeResolver
from memwing.core.scope import (
    GroupMemorySettings,
    PlatformScopeBinding,
    ProjectMemorySpace,
)
from memwing.infrastructure.db.in_memory import InMemoryDataStore
from memwing.infrastructure.platforms.feishu_connector import (
    FeishuConnector,
    compute_feishu_signature,
)


RECEIVED_AT = datetime(2026, 4, 28, 12, 0, tzinfo=UTC)
SECRET = "secret_001"


def test_feishu_webhook_ingress_writes_real_remember_event_records_from_bound_scope() -> None:
    store = _store()
    ingress_service = PlatformIngressService(
        normalizer=FeishuConnector(project_memory_space_id="project_001", signing_secret=SECRET),
        memory_gateway=MemoryGateway(store, ScopeResolver(store)),
    )
    body = json.dumps(_message_payload()).encode()
    connector = FeishuConnector(project_memory_space_id="project_001", signing_secret=SECRET)

    response = asyncio.run(
        handle_feishu_webhook(
            headers=_signed_headers(body),
            body=body,
            connector=connector,
            ingress_service=ingress_service,
            received_at=RECEIVED_AT,
        )
    )

    assert response.status_code == 202
    assert response.body["remembered"] is True
    assert len(store.source_events) == 1
    assert len(store.audit_events) == 1
    assert len(store.outbox_jobs) == 4
    source_event = store.source_events[0]
    assert response.body["source_event_id"] == source_event.id
    assert response.remember_result is not None
    assert response.remember_result.source_event_id == source_event.id
    assert source_event.project_memory_space_id == "project_001"
    assert source_event.group_id == "oc_group_001"
    assert source_event.thread_id == "om_root"
    assert source_event.shared_group_id == "shared_group_001"
    assert source_event.content == "Remember this Feishu message."
    assert source_event.metadata["source_ref"] == {
        "kind": "platform",
        "platform": "feishu",
        "tenant_id": "tenant_001",
        "channel_id": "oc_group_001",
        "thread_id": "om_root",
        "message_id": "om_001",
    }
    assert store.audit_events[0].stage == "remember_event.captured"
    assert {job.job_type for job in store.outbox_jobs} == {
        "evidence.index_source_event",
        "working_memory.append",
        "page_memory.maybe_rebuild",
        "long_term_filter.classify",
    }


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


def _store() -> InMemoryDataStore:
    store = InMemoryDataStore()
    store.add_project_memory_space(
        ProjectMemorySpace(
            id="project_001",
            name="Demo",
            default_safe_mode_enabled=False,
        )
    )
    store.add_platform_scope_binding(
        PlatformScopeBinding(
            platform="feishu",
            tenant_id="tenant_001",
            channel_id="oc_group_001",
            thread_id="om_root",
            project_memory_space_id="project_001",
            group_id="oc_group_001",
        )
    )
    store.add_group_memory_settings(
        GroupMemorySettings(
            project_memory_space_id="project_001",
            group_id="oc_group_001",
            safe_mode_enabled=False,
            shared_group_id="shared_group_001",
        )
    )
    return store
