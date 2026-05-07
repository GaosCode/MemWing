from __future__ import annotations

import json

import httpx
import pytest

from memwing.api.platform import PlatformRef
from memwing.infrastructure.platforms.feishu_openapi import (
    FeishuOpenApiError,
    FeishuOpenApiPushSender,
)


def test_feishu_openapi_sender_gets_token_and_sends_interactive_message() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/open-apis/auth/v3/tenant_access_token/internal":
            return httpx.Response(
                200,
                json={"code": 0, "msg": "ok", "tenant_access_token": "tenant_token", "expire": 7200},
            )
        if request.url.path == "/open-apis/im/v1/messages":
            assert request.url.params["receive_id_type"] == "chat_id"
            assert request.headers["Authorization"] == "Bearer tenant_token"
            body = json.loads(request.content)
            assert body["receive_id"] == "oc_group_001"
            assert body["msg_type"] == "interactive"
            assert json.loads(body["content"])["header"]["title"]["content"] == "Push title"
            assert body["uuid"] == "trace_001"
            return httpx.Response(
                200,
                json={"code": 0, "msg": "success", "data": {"message_id": "om_001"}},
            )
        raise AssertionError(f"unexpected request {request.url}")

    sender = FeishuOpenApiPushSender(
        app_id="cli_001",
        app_secret="secret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    message_id = sender.send_interactive_message(
        PlatformRef(
            platform="feishu",
            tenant_id="tenant_001",
            channel_id="oc_group_001",
            thread_id=None,
            message_id=None,
        ),
        {
            "receive_id": "oc_group_001",
            "msg_type": "interactive",
            "content": json.dumps(
                {"header": {"title": {"tag": "plain_text", "content": "Push title"}}}
            ),
        },
        "trace_001",
    )

    assert message_id == "om_001"
    assert [request.url.path for request in requests] == [
        "/open-apis/auth/v3/tenant_access_token/internal",
        "/open-apis/im/v1/messages",
    ]


def test_feishu_openapi_sender_rejects_failed_provider_response() -> None:
    sender = FeishuOpenApiPushSender(
        app_id="cli_001",
        app_secret="secret",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"code": 999, "msg": "bad auth"})
            )
        ),
    )

    with pytest.raises(FeishuOpenApiError, match="bad auth") as exc_info:
        sender.send_interactive_message(
            PlatformRef(
                platform="feishu",
                tenant_id=None,
                channel_id="oc_group_001",
                thread_id=None,
                message_id=None,
            ),
            {"receive_id": "oc_group_001", "msg_type": "interactive", "content": "{}"},
            "trace_001",
        )
    assert "code 999" in str(exc_info.value)
    assert exc_info.value.reason_code == "feishu_openapi_error"


def test_feishu_openapi_error_includes_provider_log_id() -> None:
    sender = FeishuOpenApiPushSender(
        app_id="cli_001",
        app_secret="secret",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={"code": 999, "msg": "no permission"},
                    headers={"X-Tt-Logid": "log_001"},
                )
            )
        ),
    )

    with pytest.raises(FeishuOpenApiError) as exc_info:
        sender.send_interactive_message(
            PlatformRef(
                platform="feishu",
                tenant_id=None,
                channel_id="oc_group_001",
                thread_id=None,
                message_id=None,
            ),
            {"receive_id": "oc_group_001", "msg_type": "interactive", "content": "{}"},
            "trace_001",
        )

    assert "no permission" in str(exc_info.value)
    assert "log_id=log_001" in str(exc_info.value)


def test_feishu_openapi_sender_uses_platform_ref_receive_id_type() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/open-apis/auth/v3/tenant_access_token/internal":
            return httpx.Response(
                200,
                json={"code": 0, "msg": "ok", "tenant_access_token": "tenant_token", "expire": 7200},
            )
        if request.url.path == "/open-apis/im/v1/messages":
            assert request.url.params["receive_id_type"] == "open_id"
            return httpx.Response(
                200,
                json={"code": 0, "msg": "success", "data": {"message_id": "om_001"}},
            )
        raise AssertionError(f"unexpected request {request.url}")

    sender = FeishuOpenApiPushSender(
        app_id="cli_001",
        app_secret="secret",
        receive_id_type="chat_id",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    message_id = sender.send_interactive_message(
        PlatformRef(
            platform="feishu",
            tenant_id=None,
            channel_id="ou_user_001",
            thread_id=None,
            message_id=None,
            receive_id_type="open_id",
        ),
        {"receive_id": "ou_user_001", "msg_type": "interactive", "content": "{}"},
        "trace_001",
    )

    assert message_id == "om_001"


def test_feishu_openapi_sender_validates_payload_receive_id() -> None:
    sender = FeishuOpenApiPushSender(
        app_id="cli_001",
        app_secret="secret",
        client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500))),
    )

    with pytest.raises(FeishuOpenApiError, match="receive_id"):
        sender.send_interactive_message(
            PlatformRef(
                platform="feishu",
                tenant_id=None,
                channel_id="oc_group_001",
                thread_id=None,
                message_id=None,
            ),
            {"receive_id": "oc_group_002", "msg_type": "interactive", "content": "{}"},
            "trace_001",
        )
