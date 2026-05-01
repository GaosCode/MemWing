from __future__ import annotations

from dataclasses import dataclass

from memwing.api.envelopes import ErrorResponse
from memwing.api.types import JsonObject
from memwing.application.failure_semantics import FailureClassification


@dataclass(frozen=True, slots=True)
class RenderedErrorResponse:
    status_code: int
    body: ErrorResponse


def render_error_response(
    failure: FailureClassification,
    *,
    trace_id: str | None,
) -> RenderedErrorResponse:
    return RenderedErrorResponse(
        status_code=failure.http_status,
        body=ErrorResponse(
            code=failure.reason_code,
            message=failure.safe_message,
            trace_id=trace_id,
        ),
    )


def render_error_body(
    failure: FailureClassification,
    *,
    trace_id: str | None = None,
    extra: JsonObject | None = None,
) -> JsonObject:
    response = render_error_response(failure, trace_id=trace_id).body
    body: JsonObject = {
        "ok": False,
        "code": response.code,
        "message": response.message,
    }
    if response.trace_id is not None:
        body["trace_id"] = response.trace_id
    if extra is not None:
        body.update(extra)
    return body
