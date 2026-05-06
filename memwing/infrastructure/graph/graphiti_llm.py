from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from hashlib import sha256
import json
from typing import Protocol

from graphiti_core.llm_client import LLMClient
from graphiti_core.llm_client.config import LLMConfig
from pydantic import BaseModel, ValidationError

from memwing.infrastructure.graph.graphiti_cache_context import graphiti_extraction_cache_scope
from memwing.infrastructure.llm.caching_llm import ValidatedLLMJsonCache, ValidatedLLMJsonCacheMetrics
from memwing.infrastructure.llm.errors import LLMOutputSchemaError, LLMProviderError
from memwing.infrastructure.llm.structured_output import parse_json_object
from memwing.ports.event_store import EventStoreUnitOfWorkPort
from memwing.ports.model_runtime import LLMModelClient, LLMModelRequest
from memwing.ports.model_runtime import MemWingModelRuntime, MemWingModelTransport


class GraphitiMessage(Protocol):
    role: str
    content: str


class GraphitiMemWingLLMClient(LLMClient):
    def __init__(
        self,
        client: LLMModelClient,
        *,
        cache_unit_of_work: EventStoreUnitOfWorkPort | None = None,
        cache_runtime: MemWingModelRuntime | None = None,
        cache_model: str | None = None,
        cache_transport: MemWingModelTransport | None = None,
    ) -> None:
        super().__init__(config=LLMConfig(model="memwing", small_model="memwing"))
        self._client = client
        self._cache = (
            ValidatedLLMJsonCache(
                cache_unit_of_work,
                role="graphiti_extraction",
                runtime=cache_runtime,
                model=cache_model,
                transport=cache_transport,
                prompt_hash="graphiti_extraction_prompt:v1",
                schema_hash="graphiti_extraction_schema:v1",
            )
            if cache_unit_of_work is not None
            and cache_runtime is not None
            and cache_model is not None
            and cache_transport is not None
            else None
        )
        self.cache_metrics = (
            self._cache.metrics if self._cache is not None else ValidatedLLMJsonCacheMetrics()
        )

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
        cache_scope = graphiti_extraction_cache_scope()
        prompt_hash = _prompt_hash(prompt_name)
        schema_hash = _schema_hash(response_model)
        input_text = _cache_input_text(request)
        if self._cache is not None and cache_scope is not None:
            cached = await self._cache.get(
                project_memory_space_id=cache_scope.project_memory_space_id,
                source_event_ids=cache_scope.source_event_ids,
                input_text=input_text,
                prompt_hash=prompt_hash,
                schema_hash=schema_hash,
            )
            if cached is not None:
                return _validate_parsed_response(cached, response_model=response_model)
            request = replace(
                request,
                cache_context=self._cache.context(
                    project_memory_space_id=cache_scope.project_memory_space_id,
                    source_event_ids=cache_scope.source_event_ids,
                    prompt_hash=prompt_hash,
                    schema_hash=schema_hash,
                ),
            )
        try:
            response = await self._client.complete(request)
        except LLMProviderError as exc:
            raise LLMProviderError(
                "Graphiti LLM provider request failed"
                f" prompt_name={prompt_name or 'default'}"
                f" response_model={response_model.__name__ if response_model is not None else 'none'}"
                f"; {exc}"
            ) from exc
        if self._cache is not None:
            self._cache.metrics.provider_calls += 1
        parsed = parse_json_object(response.text, source="Graphiti MemWing LLM")
        validated_json = _validate_parsed_response(parsed, response_model=response_model)
        if self._cache is not None and cache_scope is not None:
            await self._cache.put(
                project_memory_space_id=cache_scope.project_memory_space_id,
                source_event_ids=cache_scope.source_event_ids,
                input_text=input_text,
                value_json=validated_json,
                prompt_hash=prompt_hash,
                schema_hash=schema_hash,
            )
        return validated_json

    async def _generate_response(
        self,
        messages: Sequence[GraphitiMessage],
        response_model: type[BaseModel] | None = None,
        max_tokens: int | None = None,
        model_size: object | None = None,
    ) -> dict[str, object]:
        return await self.generate_response(
            messages,
            response_model=response_model,
            max_tokens=max_tokens,
            model_size=model_size,
        )


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
            "Language requirement: preserve the source language for extracted information "
            f"in group {group_id}. If the episode or memory item is mainly Chinese, all "
            "entity names, facts, summaries, attributes, and extracted relationship text "
            "must be Chinese. Do not translate Chinese source facts into English."
        )

    user_prompt = "\n\n".join(user_parts).strip()
    if not user_prompt:
        raise ValueError("Graphiti LLM wrapper requires a non-system message")

    return LLMModelRequest(
        system_prompt="\n\n".join(system_parts).strip(),
        user_prompt=user_prompt,
        trace_id=None,
    )


def _validate_parsed_response(
    parsed: dict[str, object],
    *,
    response_model: type[BaseModel] | None,
) -> dict[str, object]:
    if response_model is None:
        return parsed
    try:
        validated = response_model.model_validate(parsed)
    except ValidationError as exc:
        raise LLMOutputSchemaError(
            f"Graphiti MemWing LLM output did not match {response_model.__name__}"
        ) from exc
    return validated.model_dump(mode="json")


def _cache_input_text(request: LLMModelRequest) -> str:
    return f"system:\n{request.system_prompt}\n\nuser:\n{request.user_prompt}"


def _prompt_hash(prompt_name: str | None) -> str:
    return f"graphiti_extraction:{prompt_name or 'default'}:v2"


def _schema_hash(response_model: type[BaseModel] | None) -> str:
    if response_model is None:
        return "graphiti_extraction:none:v1"
    schema = json.dumps(response_model.model_json_schema(), sort_keys=True)
    digest = sha256(schema.encode("utf-8")).hexdigest()
    return f"graphiti_extraction:{response_model.__name__}:{digest}"


def _message_text(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Graphiti message {field} must be non-empty text")
    return value.strip()
