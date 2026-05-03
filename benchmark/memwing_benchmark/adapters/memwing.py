from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha1
import time
from typing import Any

import httpx

from memwing_benchmark.adapters.openclaw_native import MemorySearchDetails
from memwing_benchmark.config import MemWingConfig
from memwing_benchmark.errors import BenchmarkError
from memwing_benchmark.metrics.retrieval import unique_preserve_order
from memwing_benchmark.schema import BenchmarkCase, SeedMessage


INGEST_EVENT_ENDPOINT = "/v1/openclaw/events/ingest"
SEARCH_MEMORY_ENDPOINT = "/v1/memwing/tools/search-memory"
HEALTH_ENDPOINT = "/healthz"
CLEANUP_BENCHMARK_SCOPE_ENDPOINT = "/v1/memwing/admin/benchmark/cleanup-scope"
DRAIN_BENCHMARK_PIPELINE_ENDPOINT = "/v1/memwing/admin/benchmark/drain"
BENCHMARK_READINESS_ENDPOINT = "/v1/memwing/admin/benchmark/readiness"
PIPELINE_AWAIT_ENDPOINT = "/v1/memwing/pipeline/await"


@dataclass(frozen=True)
class MemWingCaseScope:
    project_memory_space_id: str
    group_id: str
    thread_id: str
    shared_group_id: str | None = None

    def payload(self) -> dict[str, str]:
        scope = {
            "project_memory_space_id": self.project_memory_space_id,
            "group_id": self.group_id,
            "thread_id": self.thread_id,
        }
        if self.shared_group_id:
            scope["shared_group_id"] = self.shared_group_id
        return scope


def memwing_case_scope(
    *,
    config: MemWingConfig,
    run_id: str,
    case_id: str,
) -> MemWingCaseScope:
    return MemWingCaseScope(
        project_memory_space_id=f"benchmark:{run_id}:{case_id}",
        group_id=f"benchmark:{case_id}",
        thread_id=f"benchmark:{case_id}",
        shared_group_id=config.shared_group_id or None,
    )


class MemWingAdapter:
    def __init__(
        self,
        config: MemWingConfig,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not config.normalized_base_url:
            raise BenchmarkError("memwing.base_url is required for --backend memwing")
        self.config = config
        self.base_url = config.normalized_base_url
        self.records: list[dict[str, Any]] = []
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(config.search_timeout_seconds),
            transport=transport,
        )

    def memory_search(self, query: str, *, max_results: int = 5) -> list[str]:
        return self.memory_search_details(query, max_results=max_results).contexts

    def health(self) -> None:
        endpoint = HEALTH_ENDPOINT
        started = time.perf_counter()
        try:
            response = self._client.get(endpoint, timeout=self.config.search_timeout_seconds)
        except httpx.TimeoutException as exc:
            latency_ms = _latency_ms(started)
            self._record_request(
                kind="health",
                method="GET",
                endpoint=endpoint,
                status_code=None,
                latency_ms=latency_ms,
                request_fields=[],
            )
            raise BenchmarkError(
                f"MemWing health check timed out: endpoint={endpoint} "
                f"timeout_seconds={self.config.search_timeout_seconds}"
            ) from exc
        except httpx.HTTPError as exc:
            latency_ms = _latency_ms(started)
            self._record_request(
                kind="health",
                method="GET",
                endpoint=endpoint,
                status_code=None,
                latency_ms=latency_ms,
                request_fields=[],
            )
            raise BenchmarkError(f"MemWing health check failed: endpoint={endpoint}") from exc

        latency_ms = _latency_ms(started)
        self._record_request(
            kind="health",
            method="GET",
            endpoint=endpoint,
            status_code=response.status_code,
            latency_ms=latency_ms,
            request_fields=[],
        )
        body = self._parse_response_body(response=response, endpoint=endpoint)
        if response.status_code < 200 or response.status_code >= 300 or body.get("ok") is not True:
            raise BenchmarkError(
                f"MemWing server is not ready: endpoint={endpoint} "
                f"status_code={response.status_code}"
            )

    def memory_search_details(
        self,
        query: str,
        *,
        limit: int | None = None,
        max_results: int | None = None,
        scope: MemWingCaseScope | None = None,
    ) -> MemorySearchDetails:
        requested_limit = limit if limit is not None else max_results
        if requested_limit is None:
            requested_limit = 5
        if requested_limit <= 0:
            raise BenchmarkError("MemWing search limit must be greater than 0")

        endpoint = SEARCH_MEMORY_ENDPOINT
        body, latency_ms = self._post_json(
            endpoint=endpoint,
            payload=self._search_payload(query=query, limit=requested_limit, scope=scope),
            timeout_seconds=self.config.search_timeout_seconds,
            request_fields=[
                "agent_id",
                "workspace_id",
                "session_id",
                "query",
                "mode",
                "limit",
                "scope",
            ],
        )

        contexts = body.get("contexts")
        results = body.get("results")
        if not isinstance(contexts, list) or not isinstance(results, list):
            raise BenchmarkError(
                f"MemWing search response does not match result shape: endpoint={endpoint}"
            )

        normalized_results = _normalize_results(results)
        return MemorySearchDetails(
            contexts=unique_preserve_order(
                [context.strip() for context in contexts if isinstance(context, str) and context.strip()]
            ),
            results=normalized_results,
            latency_ms=latency_ms,
            raw=body,
        )

    def ingest_seed_messages(
        self,
        *,
        case: BenchmarkCase,
        run_id: str,
        scope: MemWingCaseScope | None = None,
    ) -> list[dict[str, Any]]:
        ingest_records: list[dict[str, Any]] = []
        for sequence, message in enumerate(case.seed_messages):
            if not message.content.strip():
                continue
            body, latency_ms = self._post_json(
                endpoint=INGEST_EVENT_ENDPOINT,
                payload=self._ingest_payload(
                    case=case,
                    message=message,
                    run_id=run_id,
                    sequence=sequence,
                    scope=scope,
                ),
                timeout_seconds=self.config.ingest_timeout_seconds,
                request_fields=[
                    "agent_id",
                    "workspace_id",
                    "session_id",
                    "run_id",
                    "benchmark_case_id",
                    "seed_message_id",
                    "message_id",
                    "hook_name",
                    "sequence",
                    "idempotency_key",
                    "scope",
                    "content",
                    "payload",
                    "event_time",
                ],
            )
            ingest_records.append(
                {
                    "case_id": case.case_id,
                    "seed_message_id": message.id,
                    "accepted": body.get("accepted") if isinstance(body.get("accepted"), bool) else None,
                    "source_event_id": _optional_text(body.get("source_event_id")),
                    "trace_id": _optional_text(body.get("trace_id")),
                    "latency_ms": latency_ms,
                }
            )
        return ingest_records

    def cleanup_benchmark_scope(self, scope: MemWingCaseScope) -> dict[str, Any]:
        body, _latency_ms = self._post_json(
            endpoint=CLEANUP_BENCHMARK_SCOPE_ENDPOINT,
            payload={
                "agent_id": self.config.agent_id,
                "workspace_id": self.config.workspace_id,
                "session_id": self._runtime_session_id(scope),
                "scope": scope.payload(),
            },
            timeout_seconds=self.config.ingest_timeout_seconds,
            request_fields=["agent_id", "workspace_id", "session_id", "scope"],
        )
        return body

    def drain_benchmark_pipeline(
        self,
        scope: MemWingCaseScope,
        *,
        outbox_job_types: list[str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"scope": scope.payload()}
        request_fields = ["scope"]
        if outbox_job_types is not None:
            payload["outbox_job_types"] = outbox_job_types
            request_fields.append("outbox_job_types")
        body, _latency_ms = self._post_json(
            endpoint=DRAIN_BENCHMARK_PIPELINE_ENDPOINT,
            payload=payload,
            timeout_seconds=self.config.ingest_timeout_seconds,
            request_fields=request_fields,
        )
        return body

    def benchmark_readiness(
        self,
        *,
        scope: MemWingCaseScope,
        expected_source_event_ids: list[str],
        queries: list[str] | None = None,
        ignored_outbox_job_types: list[str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "scope": scope.payload(),
            "expected_source_event_ids": expected_source_event_ids,
            "queries": queries or [],
        }
        request_fields = ["scope", "expected_source_event_ids", "queries"]
        if ignored_outbox_job_types is not None:
            payload["ignored_outbox_job_types"] = ignored_outbox_job_types
            request_fields.append("ignored_outbox_job_types")
        body, _latency_ms = self._post_json(
            endpoint=BENCHMARK_READINESS_ENDPOINT,
            payload=payload,
            timeout_seconds=self.config.search_timeout_seconds,
            request_fields=request_fields,
        )
        return body

    def wait_benchmark_readiness(
        self,
        *,
        case: BenchmarkCase,
        scope: MemWingCaseScope,
        expected_source_event_ids: list[str],
        ignored_outbox_job_types: list[str] | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + self.config.poll_timeout_seconds
        attempts: list[dict[str, Any]] = []
        while True:
            readiness = self.benchmark_readiness(
                scope=scope,
                expected_source_event_ids=expected_source_event_ids,
                queries=[probe.question for probe in case.probes],
                ignored_outbox_job_types=ignored_outbox_job_types,
            )
            attempts.append(readiness)
            if readiness.get("ready") is True:
                return {
                    "case_id": case.case_id,
                    "ready": True,
                    "attempts": attempts,
                    "final": readiness,
                }
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {
                    "case_id": case.case_id,
                    "ready": False,
                    "attempts": attempts,
                    "final": readiness,
                    "timeout": True,
                }
            time.sleep(min(self.config.poll_interval_seconds, remaining))

    def pipeline_await(
        self,
        *,
        scope: MemWingCaseScope,
        source_event_ids: list[str],
        profile: str,
    ) -> dict[str, Any]:
        body, _latency_ms = self._post_json(
            endpoint=PIPELINE_AWAIT_ENDPOINT,
            payload={
                "scope": scope.payload(),
                "source_event_ids": source_event_ids,
                "profile": profile,
                "timeout_seconds": self.config.poll_timeout_seconds,
            },
            timeout_seconds=self.config.poll_timeout_seconds + self.config.search_timeout_seconds,
            request_fields=["scope", "source_event_ids", "profile", "timeout_seconds"],
        )
        return body

    def _search_payload(
        self,
        *,
        query: str,
        limit: int,
        scope: MemWingCaseScope | None,
    ) -> dict[str, Any]:
        return {
            "agent_id": self.config.agent_id,
            "workspace_id": self.config.workspace_id,
            "session_id": self._runtime_session_id(scope),
            "query": query,
            "mode": "current",
            "limit": limit,
            "scope": self._scope_payload(scope),
        }

    def _ingest_payload(
        self,
        *,
        case: BenchmarkCase,
        message: SeedMessage,
        run_id: str,
        sequence: int,
        scope: MemWingCaseScope | None,
    ) -> dict[str, Any]:
        idempotency_key = _idempotency_key(
            run_id=run_id,
            case_id=case.case_id,
            seed_message_id=message.id,
        )
        return {
            "agent_id": self.config.agent_id,
            "workspace_id": self.config.workspace_id,
            "session_id": self._runtime_session_id(scope),
            "run_id": run_id,
            "benchmark_case_id": case.case_id,
            "seed_message_id": message.id,
            "message_id": message.id,
            "hook_name": "ingest",
            "sequence": sequence,
            "idempotency_key": idempotency_key,
            "scope": self._scope_payload(scope),
            "content": message.content,
            "payload": {
                "benchmark_case_id": case.case_id,
                "seed_message_id": message.id,
                "run_id": run_id,
                "idempotency_key": idempotency_key,
                "sender": message.sender,
                "message_type": message.message_type,
                "source": message.source,
            },
            "event_time": message.time or case.case_time or datetime.now(timezone.utc).isoformat(),
        }

    def _scope_payload(self, scope: MemWingCaseScope | None = None) -> dict[str, str]:
        if scope is not None:
            return scope.payload()
        scope = {
            "project_memory_space_id": self.config.project_memory_space_id,
            "group_id": self.config.group_id,
            "thread_id": self.config.thread_id,
        }
        if self.config.shared_group_id:
            scope["shared_group_id"] = self.config.shared_group_id
        return scope

    def _runtime_session_id(self, scope: MemWingCaseScope | None) -> str:
        if scope is not None:
            return scope.thread_id
        return self.config.session_id

    def _post_json(
        self,
        *,
        endpoint: str,
        payload: dict[str, Any],
        timeout_seconds: float,
        request_fields: list[str],
    ) -> tuple[dict[str, Any], int]:
        started = time.perf_counter()
        try:
            response = self._client.post(endpoint, json=payload, timeout=timeout_seconds)
        except httpx.TimeoutException as exc:
            latency_ms = _latency_ms(started)
            self._record_request(
                kind=_request_kind(endpoint),
                method="POST",
                endpoint=endpoint,
                status_code=None,
                latency_ms=latency_ms,
                request_fields=request_fields,
            )
            raise BenchmarkError(
                f"MemWing request timed out: endpoint={endpoint} timeout_seconds={timeout_seconds}"
            ) from exc
        except httpx.HTTPError as exc:
            latency_ms = _latency_ms(started)
            self._record_request(
                kind=_request_kind(endpoint),
                method="POST",
                endpoint=endpoint,
                status_code=None,
                latency_ms=latency_ms,
                request_fields=request_fields,
            )
            raise BenchmarkError(f"MemWing request failed: endpoint={endpoint}") from exc

        latency_ms = _latency_ms(started)
        self._record_request(
            kind=_request_kind(endpoint),
            method="POST",
            endpoint=endpoint,
            status_code=response.status_code,
            latency_ms=latency_ms,
            request_fields=request_fields,
        )
        body = self._parse_response_body(response=response, endpoint=endpoint)
        trace_id = _optional_text(body.get("trace_id"))
        if trace_id:
            self.records[-1]["trace_id"] = trace_id
        if response.status_code < 200 or response.status_code >= 300:
            safe_message = _optional_text(body.get("message")) or "MemWing request failed."
            trace = f" trace_id={trace_id}" if trace_id else ""
            raise BenchmarkError(
                f"{safe_message} endpoint={endpoint} status_code={response.status_code}{trace}"
            )
        return body, latency_ms

    def _parse_response_body(
        self,
        *,
        response: httpx.Response,
        endpoint: str,
    ) -> dict[str, Any]:
        try:
            parsed = response.json()
        except ValueError as exc:
            raise BenchmarkError(
                f"MemWing response was not valid JSON: endpoint={endpoint} "
                f"status_code={response.status_code}"
            ) from exc
        if not isinstance(parsed, dict):
            raise BenchmarkError(
                f"MemWing response was not a JSON object: endpoint={endpoint} "
                f"status_code={response.status_code}"
            )
        return parsed

    def _record_request(
        self,
        *,
        kind: str,
        method: str,
        endpoint: str,
        status_code: int | None,
        latency_ms: int,
        request_fields: list[str],
        trace_id: str | None = None,
    ) -> None:
        record: dict[str, Any] = {
            "kind": kind,
            "method": method,
            "endpoint": endpoint,
            "status_code": status_code,
            "latency_ms": latency_ms,
            "request_fields": request_fields,
        }
        if trace_id:
            record["trace_id"] = trace_id
        self.records.append(record)


def _normalize_results(results: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(results, start=1):
        if not isinstance(item, dict):
            raise BenchmarkError("MemWing search result item must be a JSON object")
        text = _required_text(item.get("text"), "results.text")
        normalized.append(
            {
                "rank": index,
                "id": _optional_text(item.get("id")),
                "path": _optional_text(item.get("path")),
                "startLine": _optional_int(item.get("startLine")),
                "endLine": _optional_int(item.get("endLine")),
                "score": _optional_float(item.get("score")),
                "vectorScore": _optional_float(item.get("vectorScore")),
                "textScore": _optional_float(item.get("textScore")),
                "source": _optional_text(item.get("source")),
                "snippet": text,
                "source_event_ids": _text_list(item.get("source_event_ids")),
                "memory_item_ids": _text_list(item.get("memory_item_ids")),
                "valid_from": _optional_text(item.get("valid_from")),
                "valid_to": _optional_text(item.get("valid_to")),
                "metadata": item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                "raw": item,
            }
        )
    return normalized


def _request_kind(endpoint: str) -> str:
    if endpoint == SEARCH_MEMORY_ENDPOINT:
        return "search"
    if endpoint == INGEST_EVENT_ENDPOINT:
        return "ingest"
    if endpoint == HEALTH_ENDPOINT:
        return "health"
    if endpoint == CLEANUP_BENCHMARK_SCOPE_ENDPOINT:
        return "benchmark_cleanup"
    if endpoint == DRAIN_BENCHMARK_PIPELINE_ENDPOINT:
        return "benchmark_drain"
    if endpoint == BENCHMARK_READINESS_ENDPOINT:
        return "benchmark_readiness"
    if endpoint == PIPELINE_AWAIT_ENDPOINT:
        return "pipeline_await"
    return "http"


def _latency_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def _idempotency_key(*, run_id: str, case_id: str, seed_message_id: str) -> str:
    digest = sha1(f"{run_id}:{case_id}:{seed_message_id}".encode("utf-8")).hexdigest()[:12]
    return f"mwb:{case_id}:{seed_message_id}:{digest}"


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkError(f"MemWing search response is missing {field_name}")
    return value.strip()


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, int | float) else None


def _text_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
