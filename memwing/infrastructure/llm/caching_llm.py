from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
import uuid

from memwing.ports.event_store import EventStoreUnitOfWorkPort
from memwing.ports.model_result_cache import ModelResultCacheEntry, ModelResultCacheKey
from memwing.ports.model_runtime import (
    MemWingModelRole,
    MemWingModelRuntime,
    MemWingModelTransport,
    ModelCacheContext,
)


@dataclass(slots=True)
class ValidatedLLMJsonCacheMetrics:
    hits: int = 0
    misses: int = 0
    puts: int = 0
    invalidations: int = 0
    bypasses: int = 0
    provider_calls: int = 0


class ValidatedLLMJsonCache:
    def __init__(
        self,
        unit_of_work: EventStoreUnitOfWorkPort,
        *,
        role: MemWingModelRole,
        runtime: MemWingModelRuntime,
        model: str,
        transport: MemWingModelTransport,
        prompt_hash: str,
        schema_hash: str,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._role = role
        self._runtime = runtime
        self._model = model
        self._transport = transport
        self._prompt_hash = prompt_hash
        self._schema_hash = schema_hash
        self._now = now or (lambda: datetime.now(UTC))
        self.metrics = ValidatedLLMJsonCacheMetrics()

    async def get(
        self,
        *,
        project_memory_space_id: str,
        source_event_ids: tuple[str, ...],
        input_text: str,
        prompt_hash: str | None = None,
        schema_hash: str | None = None,
    ) -> dict[str, object] | None:
        if not source_event_ids:
            self.metrics.bypasses += 1
            return None
        key = self._key(
            project_memory_space_id=project_memory_space_id,
            input_text=input_text,
            prompt_hash=prompt_hash,
            schema_hash=schema_hash,
        )
        async with self._unit_of_work.transaction() as tx:
            hit = await tx.model_result_cache.get(key=key, now=self._now())
        if hit is None:
            self.metrics.misses += 1
            return None
        merged_source_event_ids = _merge_source_event_ids(hit.source_event_ids, source_event_ids)
        if merged_source_event_ids != hit.source_event_ids:
            async with self._unit_of_work.transaction() as tx:
                await tx.model_result_cache.put(
                    replace(hit, source_event_ids=merged_source_event_ids)
                )
        self.metrics.hits += 1
        return hit.value_json

    async def put(
        self,
        *,
        project_memory_space_id: str,
        source_event_ids: tuple[str, ...],
        input_text: str,
        value_json: dict[str, object],
        prompt_hash: str | None = None,
        schema_hash: str | None = None,
    ) -> None:
        if not source_event_ids:
            self.metrics.bypasses += 1
            return
        now = self._now()
        entry = ModelResultCacheEntry(
            id=str(uuid.uuid4()),
            key=self._key(
                project_memory_space_id=project_memory_space_id,
                input_text=input_text,
                prompt_hash=prompt_hash,
                schema_hash=schema_hash,
            ),
            source_event_ids=source_event_ids,
            value_json=value_json,
            embedding_vector=None,
            status="active",
            created_at=now,
            last_hit_at=None,
            hit_count=0,
            invalidated_at=None,
            invalidated_reason=None,
            expires_at=None,
        )
        async with self._unit_of_work.transaction() as tx:
            await tx.model_result_cache.put(entry)
        self.metrics.puts += 1

    def context(
        self,
        *,
        project_memory_space_id: str,
        source_event_ids: tuple[str, ...],
        prompt_hash: str | None = None,
        schema_hash: str | None = None,
    ) -> ModelCacheContext:
        return ModelCacheContext(
            project_memory_space_id=project_memory_space_id,
            source_event_ids=source_event_ids,
            role=self._role,
            prompt_hash=prompt_hash or self._prompt_hash,
            schema_hash=schema_hash or self._schema_hash,
            cache_policy="required",
        )

    def _key(
        self,
        *,
        project_memory_space_id: str,
        input_text: str,
        prompt_hash: str | None = None,
        schema_hash: str | None = None,
    ) -> ModelResultCacheKey:
        return ModelResultCacheKey(
            project_memory_space_id=project_memory_space_id,
            cache_kind="llm_json",
            role=self._role,
            runtime=self._runtime,
            model=self._model,
            transport=self._transport,
            prompt_hash=prompt_hash or self._prompt_hash,
            input_hash=sha256(input_text.encode("utf-8")).hexdigest(),
            schema_hash=schema_hash or self._schema_hash,
        )


def _merge_source_event_ids(
    first: tuple[str, ...],
    second: tuple[str, ...],
) -> tuple[str, ...]:
    return tuple(sorted({*first, *second}))
