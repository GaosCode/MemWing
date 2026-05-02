from psycopg.types.json import Jsonb

from memwing.infrastructure.db.postgres_connection import _prepare_params, _prepare_sql
from memwing.infrastructure.db.postgres_derived_sql import _LIST_MEMORY_ITEMS_FOR_SCOPE_SQL
from memwing.infrastructure.db.postgres_sql import _LIST_RECENT_SOURCE_EVENTS_FOR_SCOPE_SQL


def test_prepare_sql_escapes_literal_percent_without_changing_placeholders() -> None:
    sql = """
    SELECT *
    FROM runtime_scope_bindings
    WHERE runtime = %(runtime)s
      AND COALESCE(%(session_id)s, '') LIKE replace(session_key_pattern, '%', '!%')
      AND note LIKE %s
      AND raw_payload_hash = %(raw_payload_hash)s
    """

    prepared = _prepare_sql(sql)

    assert "%(runtime)s" in prepared
    assert "%(session_id)s" in prepared
    assert "%(raw_payload_hash)s" in prepared
    assert "LIKE %s" in prepared
    assert "replace(session_key_pattern, '%%', '!%%')" in prepared


def test_prepare_params_wraps_json_columns_without_touching_arrays() -> None:
    prepared = _prepare_params(
        {
            "metadata_json": {"case_id": "bs001"},
            "topics_json": [{"title": "scope"}],
            "source_event_ids": ("source_event_001",),
        }
    )

    assert isinstance(prepared["metadata_json"], Jsonb)
    assert isinstance(prepared["topics_json"], Jsonb)
    assert prepared["source_event_ids"] == ["source_event_001"]


def test_scope_queries_cast_nullable_group_id_arrays() -> None:
    assert "%(group_ids)s::text[] IS NULL" in _LIST_MEMORY_ITEMS_FOR_SCOPE_SQL
    assert "ANY(%(group_ids)s::text[])" in _LIST_MEMORY_ITEMS_FOR_SCOPE_SQL
    assert "%(thread_id)s::text IS NULL" in _LIST_MEMORY_ITEMS_FOR_SCOPE_SQL
    assert "%(shared_group_id)s::text IS NULL" in _LIST_MEMORY_ITEMS_FOR_SCOPE_SQL
    assert "%(group_ids)s::text[] IS NULL" in _LIST_RECENT_SOURCE_EVENTS_FOR_SCOPE_SQL
    assert "ANY(%(group_ids)s::text[])" in _LIST_RECENT_SOURCE_EVENTS_FOR_SCOPE_SQL
    assert "%(thread_id)s::text IS NULL" in _LIST_RECENT_SOURCE_EVENTS_FOR_SCOPE_SQL
    assert "%(shared_group_id)s::text IS NULL" in _LIST_RECENT_SOURCE_EVENTS_FOR_SCOPE_SQL
