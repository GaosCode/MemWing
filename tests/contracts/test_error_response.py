from memwing.api.error_mapping import render_error_response
from memwing.application.failure_semantics import classify_failure
from memwing.core.errors import ScopeResolutionFailure


def test_error_response_renders_failure_classification_safely() -> None:
    failure = classify_failure(
        RuntimeError("raw source event content must not leak"),
        audit_stage="api.recall",
    )

    response = render_error_response(failure, trace_id="trace_001")

    assert response.status_code == 500
    assert response.body.code == "unexpected_failure"
    assert response.body.message == "The operation failed unexpectedly."
    assert response.body.trace_id == "trace_001"
    assert "raw source event content" not in response.body.message


def test_scope_resolution_error_response_does_not_reveal_object_existence() -> None:
    failure = classify_failure(
        ScopeResolutionFailure("scope_not_found", "Memory scope is not available."),
        audit_stage="api.memory_detail",
    )

    response = render_error_response(failure, trace_id="trace_scope")

    assert response.status_code == 404
    assert response.body.code == "scope_not_found"
    assert response.body.message == "Memory scope is not available."
    assert response.body.trace_id == "trace_scope"
