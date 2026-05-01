from __future__ import annotations

from dataclasses import dataclass

from memwing.api.envelopes import ErrorResponse
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
