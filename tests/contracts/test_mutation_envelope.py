import pytest

from memwing.api.schemas import MutationEnvelope, SchemaValidationError


def test_mutation_envelope_requires_actor_reason_and_idempotency_key() -> None:
    envelope = MutationEnvelope(
        actor_id="user_001",
        reason="confirm memory",
        idempotency_key="confirm-memory-001",
    )

    assert envelope.actor_id == "user_001"
    assert envelope.reason == "confirm memory"
    assert envelope.idempotency_key == "confirm-memory-001"
    assert envelope.trace_id is None

    with pytest.raises(SchemaValidationError, match="actor_id"):
        MutationEnvelope(actor_id="", reason="confirm memory", idempotency_key="confirm-001")

    with pytest.raises(SchemaValidationError, match="reason"):
        MutationEnvelope(actor_id="user_001", reason="", idempotency_key="confirm-001")

    with pytest.raises(SchemaValidationError, match="idempotency_key"):
        MutationEnvelope(actor_id="user_001", reason="confirm memory", idempotency_key="")
