import pytest

from memwing.api.schemas import ErrorResponse, ListResponse, SchemaValidationError


def test_error_response_and_list_response_use_shared_envelopes() -> None:
    error = ErrorResponse(code="scope_conflict", message="scope is invalid", trace_id="trace_001")
    response = ListResponse(items=("memory_001",), next_cursor="cursor_002", trace_id="trace_001")

    assert error.code == "scope_conflict"
    assert error.message == "scope is invalid"
    assert error.trace_id == "trace_001"
    assert response.items == ("memory_001",)
    assert response.next_cursor == "cursor_002"
    assert response.trace_id == "trace_001"

    with pytest.raises(SchemaValidationError, match="code"):
        ErrorResponse(code="", message="scope is invalid")

    with pytest.raises(SchemaValidationError, match="message"):
        ErrorResponse(code="scope_conflict", message="")
