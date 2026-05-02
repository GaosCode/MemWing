from __future__ import annotations

import time
from typing import Any

import httpx

from memwing_benchmark.adapters.openclaw_native import MemorySearchDetails
from memwing_benchmark.config import MemWingConfig
from memwing_benchmark.errors import BenchmarkError
from memwing_benchmark.metrics.retrieval import unique_preserve_order


SEARCH_MEMORY_ENDPOINT = "/v1/memwing/tools/search-memory"


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

    def memory_search_details(
        self,
        query: str,
        *,
        limit: int | None = None,
        max_results: int | None = None,
    ) -> MemorySearchDetails:
        requested_limit = limit if limit is not None else max_results
        if requested_limit is None:
            requested_limit = 5
        if requested_limit <= 0:
            raise BenchmarkError("MemWing search limit must be greater than 0")

        endpoint = SEARCH_MEMORY_ENDPOINT
        payload = self._search_payload(query=query, limit=requested_limit)
        started = time.perf_counter()
        try:
            response = self._client.post(endpoint, json=payload)
        except httpx.TimeoutException as exc:
            latency_ms = _latency_ms(started)
            self._record_request(endpoint=endpoint, status_code=None, latency_ms=latency_ms)
            raise BenchmarkError(
                f"MemWing request timed out: endpoint={endpoint} timeout_seconds="
                f"{self.config.search_timeout_seconds}"
            ) from exc
        except httpx.HTTPError as exc:
            latency_ms = _latency_ms(started)
            self._record_request(endpoint=endpoint, status_code=None, latency_ms=latency_ms)
            raise BenchmarkError(f"MemWing request failed: endpoint={endpoint}") from exc

        latency_ms = _latency_ms(started)
        self._record_request(
            endpoint=endpoint,
            status_code=response.status_code,
            latency_ms=latency_ms,
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

    def _search_payload(self, *, query: str, limit: int) -> dict[str, Any]:
        scope = {
            "project_memory_space_id": self.config.project_memory_space_id,
            "group_id": self.config.group_id,
            "thread_id": self.config.thread_id,
        }
        if self.config.shared_group_id:
            scope["shared_group_id"] = self.config.shared_group_id
        return {
            "agent_id": self.config.agent_id,
            "workspace_id": self.config.workspace_id,
            "session_id": self.config.session_id,
            "query": query,
            "mode": "current",
            "limit": limit,
            "scope": scope,
        }

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
        endpoint: str,
        status_code: int | None,
        latency_ms: int,
        trace_id: str | None = None,
    ) -> None:
        record: dict[str, Any] = {
            "method": "POST",
            "endpoint": endpoint,
            "status_code": status_code,
            "latency_ms": latency_ms,
            "request_fields": [
                "agent_id",
                "workspace_id",
                "session_id",
                "query",
                "mode",
                "limit",
                "scope",
            ],
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


def _latency_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


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
