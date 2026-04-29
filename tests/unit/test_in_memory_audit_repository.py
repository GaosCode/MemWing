import asyncio

from dataclasses import replace

from memwing.infrastructure.db.in_memory import InMemoryDataStore

from tests.unit.postgres_store_fixtures import audit_event, source_event


def test_in_memory_audit_record_is_idempotent_for_matching_entity_key() -> None:
    store = InMemoryDataStore()
    source = source_event()
    audit = audit_event(source)

    async def scenario() -> None:
        async with store.transaction() as tx:
            first = await tx.audit_events.record(audit)
            duplicate = await tx.audit_events.record(
                replace(audit, id="audit_duplicate", decision="duplicate")
            )
            loaded = await tx.audit_events.get_by_idempotency_key(
                entity_type=audit.entity_type,
                entity_id=audit.entity_id,
                idempotency_key="audit:source_001",
            )

        assert first == audit
        assert duplicate == audit
        assert loaded == audit

    asyncio.run(scenario())

    assert store.audit_events == (audit,)
