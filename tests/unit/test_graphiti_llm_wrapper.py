from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
from pydantic import BaseModel

from memwing.infrastructure.graph.graphiti_llm import GraphitiMemWingLLMClient
from memwing.infrastructure.llm.errors import LLMOutputSchemaError
from memwing.ports.model_runtime import LLMModelRequest, LLMModelResponse


@dataclass(frozen=True, slots=True)
class Message:
    role: str
    content: str


class FakeLLMClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.requests: list[LLMModelRequest] = []

    async def complete(self, request: LLMModelRequest) -> LLMModelResponse:
        self.requests.append(request)
        return LLMModelResponse(text=self.text, provider="fake", model="fake-model")


class ExtractedPayload(BaseModel):
    ok: bool
    count: int


def test_graphiti_llm_wrapper_validates_response_model() -> None:
    fake = FakeLLMClient('{"ok": true, "count": 2}')
    wrapper = GraphitiMemWingLLMClient(fake)

    async def scenario() -> dict[str, object]:
        return await wrapper.generate_response(
            [
                Message(role="system", content="Extract graph facts."),
                Message(role="user", content="Alice owns the roadmap."),
            ],
            response_model=ExtractedPayload,
            group_id="project_001",
        )

    response = asyncio.run(scenario())

    assert response == {"ok": True, "count": 2}
    assert fake.requests == [
        LLMModelRequest(
            system_prompt="Extract graph facts.",
            user_prompt=(
                "user:\nAlice owns the roadmap.\n\n"
                "Respond with a JSON object matching this schema:\n"
                '{"properties": {"ok": {"title": "Ok", "type": "boolean"}, '
                '"count": {"title": "Count", "type": "integer"}}, '
                '"required": ["ok", "count"], "title": "ExtractedPayload", "type": "object"}\n\n'
                "Preserve the source language for extracted information in group project_001."
            ),
            trace_id=None,
        )
    ]


def test_graphiti_llm_wrapper_combines_non_system_messages_in_order() -> None:
    fake = FakeLLMClient('{"ok": true}')
    wrapper = GraphitiMemWingLLMClient(fake)

    async def scenario() -> None:
        await wrapper.generate_response(
            [
                Message(role="system", content="System one."),
                Message(role="system", content="System two."),
                Message(role="user", content="First."),
                Message(role="assistant", content="Second."),
            ],
        )

    asyncio.run(scenario())

    assert fake.requests[0].system_prompt == "System one.\n\nSystem two."
    assert fake.requests[0].user_prompt == "user:\nFirst.\n\nassistant:\nSecond."


def test_graphiti_llm_wrapper_rejects_bad_json() -> None:
    fake = FakeLLMClient("not-json secret-token")
    wrapper = GraphitiMemWingLLMClient(fake)

    async def scenario() -> None:
        await wrapper.generate_response([Message(role="user", content="Ping")])

    with pytest.raises(LLMOutputSchemaError) as exc_info:
        asyncio.run(scenario())

    assert "secret-token" not in str(exc_info.value)


def test_graphiti_llm_wrapper_rejects_schema_mismatch() -> None:
    fake = FakeLLMClient('{"ok": true}')
    wrapper = GraphitiMemWingLLMClient(fake)

    async def scenario() -> None:
        await wrapper.generate_response(
            [Message(role="user", content="Ping")],
            response_model=ExtractedPayload,
        )

    with pytest.raises(LLMOutputSchemaError, match="did not match ExtractedPayload"):
        asyncio.run(scenario())
