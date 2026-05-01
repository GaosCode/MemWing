from __future__ import annotations

from collections.abc import Sequence
import json
from typing import Protocol

from pydantic import BaseModel, ValidationError

from memwing.infrastructure.llm.errors import LLMOutputSchemaError
from memwing.infrastructure.llm.structured_output import parse_json_object
from memwing.ports.model_runtime import LLMModelClient, LLMModelRequest


class GraphitiMessage(Protocol):
    role: str
    content: str


class GraphitiMemWingLLMClient:
    def __init__(self, client: LLMModelClient) -> None:
        self._client = client

    async def generate_response(
        self,
        messages: Sequence[GraphitiMessage],
        response_model: type[BaseModel] | None = None,
        max_tokens: int | None = None,
        model_size: object | None = None,
        group_id: str | None = None,
        prompt_name: str | None = None,
    ) -> dict[str, object]:
        request = _request_from_messages(messages, response_model=response_model, group_id=group_id)
        response = await self._client.complete(request)
        parsed = parse_json_object(response.text, source="Graphiti MemWing LLM")
        if response_model is None:
            return parsed
        try:
            validated = response_model.model_validate(parsed)
        except ValidationError as exc:
            raise LLMOutputSchemaError(
                f"Graphiti MemWing LLM output did not match {response_model.__name__}"
            ) from exc
        return validated.model_dump(mode="json")


def _request_from_messages(
    messages: Sequence[GraphitiMessage],
    *,
    response_model: type[BaseModel] | None,
    group_id: str | None,
) -> LLMModelRequest:
    if not messages:
        raise ValueError("Graphiti LLM wrapper requires at least one message")

    system_parts: list[str] = []
    user_parts: list[str] = []
    for message in messages:
        role = _message_text(message.role, field="role").lower()
        content = _message_text(message.content, field="content")
        if role == "system":
            system_parts.append(content)
        else:
            user_parts.append(f"{role}:\n{content}")

    if response_model is not None:
        schema = json.dumps(response_model.model_json_schema())
        user_parts.append(f"Respond with a JSON object matching this schema:\n{schema}")
    if group_id is not None:
        user_parts.append(
            f"Preserve the source language for extracted information in group {group_id}."
        )

    user_prompt = "\n\n".join(user_parts).strip()
    if not user_prompt:
        raise ValueError("Graphiti LLM wrapper requires a non-system message")

    return LLMModelRequest(
        system_prompt="\n\n".join(system_parts).strip(),
        user_prompt=user_prompt,
        trace_id=None,
    )


def _message_text(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Graphiti message {field} must be non-empty text")
    return value.strip()
