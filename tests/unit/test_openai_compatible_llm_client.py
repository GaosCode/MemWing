import asyncio

import pytest

from memwing.infrastructure.llm.errors import LLMOutputSchemaError, LLMProviderError
from memwing.infrastructure.llm.model_client import LLMModelRequest
from memwing.infrastructure.llm.openai_compatible import (
    OpenAICompatibleChatClient,
    OpenAICompatibleConfig,
)


class FakeTransport:
    def __init__(
        self,
        *,
        response: dict[str, object] | None = None,
        fail_statuses: tuple[int, ...] = (),
    ) -> None:
        self.response = response or {
            "choices": [{"message": {"content": '{"ok":true}'}}],
        }
        self.fail_statuses = list(fail_statuses)
        self.requests: list[dict[str, object]] = []

    def post_json(self, *, url, headers, payload, timeout_seconds):
        self.requests.append(
            {
                "url": url,
                "headers": dict(headers),
                "payload": dict(payload),
                "timeout_seconds": timeout_seconds,
            }
        )
        if self.fail_statuses:
            from memwing.infrastructure.llm.openai_compatible import _OpenAICompatibleHTTPError

            raise _OpenAICompatibleHTTPError(self.fail_statuses.pop(0))
        return self.response


def test_openai_compatible_client_posts_chat_completion_payload() -> None:
    transport = FakeTransport()
    client = OpenAICompatibleChatClient(
        OpenAICompatibleConfig(
            api_key="key_123",
            base_url="https://example.test/v1",
            model="model-a",
            timeout_seconds=12,
        ),
        transport=transport,
    )

    async def scenario():
        return await client.complete(
            LLMModelRequest(
                system_prompt="Return JSON.",
                user_prompt="Ping",
                trace_id="trace_001",
            )
        )

    response = asyncio.run(scenario())

    assert response.text == '{"ok":true}'
    assert response.provider == "openai-compatible"
    assert transport.requests == [
        {
            "url": "https://example.test/v1/chat/completions",
            "headers": {
                "Authorization": "Bearer key_123",
                "Content-Type": "application/json",
            },
            "payload": {
                "model": "model-a",
                "messages": (
                    {"role": "system", "content": "Return JSON."},
                    {"role": "user", "content": "Ping"},
                ),
                "temperature": 0.0,
            },
            "timeout_seconds": 12,
        }
    ]


def test_openai_compatible_client_retries_without_response_format_for_422() -> None:
    transport = FakeTransport(fail_statuses=(422,))
    client = OpenAICompatibleChatClient(
        OpenAICompatibleConfig(
            api_key="key_123",
            base_url="https://example.test/v1",
            model="model-a",
            response_format_json=True,
        ),
        transport=transport,
    )

    async def scenario():
        return await client.complete(
            LLMModelRequest(system_prompt="Return JSON.", user_prompt="Ping", trace_id=None)
        )

    response = asyncio.run(scenario())

    assert response.text == '{"ok":true}'
    assert transport.requests[0]["payload"]["response_format"] == {"type": "json_object"}
    assert "response_format" not in transport.requests[1]["payload"]


def test_openai_compatible_client_maps_provider_http_error_without_body_leak() -> None:
    transport = FakeTransport(fail_statuses=(500,))
    client = OpenAICompatibleChatClient(
        OpenAICompatibleConfig(
            api_key="key_123",
            base_url="https://example.test/v1",
            model="model-a",
        ),
        transport=transport,
    )

    async def scenario():
        return await client.complete(
            LLMModelRequest(system_prompt="Return JSON.", user_prompt="Ping", trace_id=None)
        )

    with pytest.raises(LLMProviderError, match="HTTP 500"):
        asyncio.run(scenario())


def test_openai_compatible_client_rejects_malformed_response() -> None:
    client = OpenAICompatibleChatClient(
        OpenAICompatibleConfig(
            api_key="key_123",
            base_url="https://example.test/v1",
            model="model-a",
        ),
        transport=FakeTransport(response={"choices": []}),
    )

    async def scenario():
        return await client.complete(
            LLMModelRequest(system_prompt="Return JSON.", user_prompt="Ping", trace_id=None)
        )

    with pytest.raises(LLMOutputSchemaError, match="requires choices"):
        asyncio.run(scenario())
