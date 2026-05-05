from __future__ import annotations

from datetime import datetime

from memwing.ports.model_result_cache import ModelResultCacheEntry, ModelResultCacheKey

from .postgres_repositories import PostgresExecutor
from .postgres_rows import (
    Row,
    _datetime,
    _dict,
    _float_sequence_or_none,
    _int,
    _optional_datetime,
    _optional_text,
    _sequence,
    _text,
)


class PostgresModelResultCacheRepository:
    def __init__(self, executor: PostgresExecutor) -> None:
        self._executor = executor

    async def get(
        self,
        *,
        key: ModelResultCacheKey,
        now: datetime,
    ) -> ModelResultCacheEntry | None:
        row = await self._executor.fetchrow(
            """
            UPDATE model_result_cache
            SET hit_count = model_result_cache.hit_count + 1,
                last_hit_at = %(now)s
            WHERE project_memory_space_id = %(project_memory_space_id)s
              AND cache_kind = %(cache_kind)s
              AND role = %(role)s
              AND runtime = %(runtime)s
              AND model = %(model)s
              AND transport = %(transport)s
              AND prompt_hash = %(prompt_hash)s
              AND input_hash = %(input_hash)s
              AND schema_hash = %(schema_hash)s
              AND status = 'active'
              AND (expires_at IS NULL OR expires_at > %(now)s)
            RETURNING *
            """,
            {**_key_params(key), "now": now},
        )
        return _entry_from_row(row) if row is not None else None

    async def put(self, entry: ModelResultCacheEntry) -> ModelResultCacheEntry:
        row = await self._executor.fetchrow(
            """
            INSERT INTO model_result_cache (
                id,
                project_memory_space_id,
                cache_kind,
                role,
                runtime,
                model,
                transport,
                prompt_hash,
                input_hash,
                schema_hash,
                source_event_ids,
                value_json,
                embedding_vector,
                status,
                created_at,
                last_hit_at,
                hit_count,
                invalidated_at,
                invalidated_reason,
                expires_at
            )
            VALUES (
                %(id)s,
                %(project_memory_space_id)s,
                %(cache_kind)s,
                %(role)s,
                %(runtime)s,
                %(model)s,
                %(transport)s,
                %(prompt_hash)s,
                %(input_hash)s,
                %(schema_hash)s,
                %(source_event_ids)s,
                %(value_json)s,
                %(embedding_vector)s,
                %(status)s,
                %(created_at)s,
                %(last_hit_at)s,
                %(hit_count)s,
                %(invalidated_at)s,
                %(invalidated_reason)s,
                %(expires_at)s
            )
            ON CONFLICT (
                project_memory_space_id,
                cache_kind,
                role,
                runtime,
                model,
                transport,
                prompt_hash,
                input_hash,
                schema_hash
            )
            DO UPDATE SET
                source_event_ids = EXCLUDED.source_event_ids,
                value_json = EXCLUDED.value_json,
                embedding_vector = EXCLUDED.embedding_vector,
                status = EXCLUDED.status,
                invalidated_at = EXCLUDED.invalidated_at,
                invalidated_reason = EXCLUDED.invalidated_reason,
                expires_at = EXCLUDED.expires_at
            RETURNING *
            """,
            _entry_params(entry),
        )
        if row is None:
            raise RuntimeError("model result cache upsert did not return a row")
        return _entry_from_row(row)

    async def list_by_source_event(
        self,
        *,
        project_memory_space_id: str,
        source_event_id: str,
    ) -> tuple[ModelResultCacheEntry, ...]:
        rows = await self._executor.fetch(
            """
            SELECT *
            FROM model_result_cache
            WHERE project_memory_space_id = %(project_memory_space_id)s
              AND %(source_event_id)s = ANY(source_event_ids)
            ORDER BY created_at ASC, id ASC
            """,
            {
                "project_memory_space_id": project_memory_space_id,
                "source_event_id": source_event_id,
            },
        )
        return tuple(_entry_from_row(row) for row in rows)

    async def invalidate_source_event(
        self,
        *,
        project_memory_space_id: str,
        source_event_id: str,
        invalidated_at: datetime,
        reason: str,
    ) -> int:
        row = await self._executor.fetchrow(
            """
            WITH updated AS (
                UPDATE model_result_cache
                SET status = 'invalidated',
                    invalidated_at = %(invalidated_at)s,
                    invalidated_reason = %(reason)s
                WHERE project_memory_space_id = %(project_memory_space_id)s
                  AND %(source_event_id)s = ANY(source_event_ids)
                  AND status = 'active'
                RETURNING 1
            )
            SELECT count(*) AS invalidated_count FROM updated
            """,
            {
                "project_memory_space_id": project_memory_space_id,
                "source_event_id": source_event_id,
                "invalidated_at": invalidated_at,
                "reason": reason,
            },
        )
        return 0 if row is None else _int(row, "invalidated_count")


def _entry_from_row(row: Row) -> ModelResultCacheEntry:
    return ModelResultCacheEntry(
        id=_text(row, "id"),
        key=ModelResultCacheKey(
            project_memory_space_id=_text(row, "project_memory_space_id"),
            cache_kind=_text(row, "cache_kind"),  # type: ignore[arg-type]
            role=_text(row, "role"),  # type: ignore[arg-type]
            runtime=_text(row, "runtime"),  # type: ignore[arg-type]
            model=_text(row, "model"),
            transport=_text(row, "transport"),  # type: ignore[arg-type]
            prompt_hash=_text(row, "prompt_hash"),
            input_hash=_text(row, "input_hash"),
            schema_hash=_text(row, "schema_hash"),
        ),
        source_event_ids=_sequence(row, "source_event_ids"),
        value_json=_dict(row, "value_json"),
        embedding_vector=_float_sequence_or_none(row, "embedding_vector"),
        status=_text(row, "status"),  # type: ignore[arg-type]
        created_at=_datetime(row, "created_at"),
        last_hit_at=_optional_datetime(row, "last_hit_at"),
        hit_count=_int(row, "hit_count"),
        invalidated_at=_optional_datetime(row, "invalidated_at"),
        invalidated_reason=_optional_text(row, "invalidated_reason"),
        expires_at=_optional_datetime(row, "expires_at"),
    )


def _entry_params(entry: ModelResultCacheEntry) -> dict[str, object]:
    return {
        "id": entry.id,
        **_key_params(entry.key),
        "source_event_ids": entry.source_event_ids,
        "value_json": entry.value_json,
        "embedding_vector": entry.embedding_vector,
        "status": entry.status,
        "created_at": entry.created_at,
        "last_hit_at": entry.last_hit_at,
        "hit_count": entry.hit_count,
        "invalidated_at": entry.invalidated_at,
        "invalidated_reason": entry.invalidated_reason,
        "expires_at": entry.expires_at,
    }


def _key_params(key: ModelResultCacheKey) -> dict[str, object]:
    return {
        "project_memory_space_id": key.project_memory_space_id,
        "cache_kind": key.cache_kind,
        "role": key.role,
        "runtime": key.runtime,
        "model": key.model,
        "transport": key.transport,
        "prompt_hash": key.prompt_hash,
        "input_hash": key.input_hash,
        "schema_hash": key.schema_hash,
    }
