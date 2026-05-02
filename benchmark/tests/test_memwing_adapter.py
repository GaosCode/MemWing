import json

import httpx
import pytest

from memwing_benchmark.adapters.memwing import SEARCH_MEMORY_ENDPOINT, MemWingAdapter
from memwing_benchmark.config import MemWingConfig
from memwing_benchmark.errors import BenchmarkError


def test_memory_search_details_posts_to_memwing_tool_url_and_maps_results() -> None:
    seen_payloads = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_payloads.append(json.loads(request.content))
        assert request.url.path == SEARCH_MEMORY_ENDPOINT
        return httpx.Response(
            200,
            json={
                "contexts": ["负责人是沈南。", "负责人是沈南。"],
                "results": [
                    {
                        "id": "result_001",
                        "text": "负责人是沈南。",
                        "score": 0.91,
                        "source": "memory_item",
                        "source_event_ids": ["bs001_s1"],
                        "memory_item_ids": ["mem_001"],
                        "valid_from": "2026-05-02T00:00:00+00:00",
                        "valid_to": None,
                        "metadata": {"route": "long_term"},
                    }
                ],
                "next_cursor": None,
                "trace_id": "trace_search",
            },
        )

    adapter = MemWingAdapter(_config(), transport=httpx.MockTransport(handler))

    details = adapter.memory_search_details("谁负责？", limit=5)

    assert seen_payloads == [
        {
            "agent_id": "main",
            "workspace_id": "workspace_001",
            "session_id": "memwing-benchmark",
            "query": "谁负责？",
            "mode": "current",
            "limit": 5,
            "scope": {
                "project_memory_space_id": "project_001",
                "group_id": "benchmark_group",
                "thread_id": "benchmark_thread",
            },
        }
    ]
    assert details.contexts == ["负责人是沈南。"]
    assert details.results[0]["id"] == "result_001"
    assert details.results[0]["score"] == 0.91
    assert details.results[0]["snippet"] == "负责人是沈南。"
    assert details.results[0]["source_event_ids"] == ["bs001_s1"]
    assert details.results[0]["memory_item_ids"] == ["mem_001"]
    assert details.raw["trace_id"] == "trace_search"
    assert adapter.records == [
        {
            "method": "POST",
            "endpoint": SEARCH_MEMORY_ENDPOINT,
            "status_code": 200,
            "latency_ms": details.latency_ms,
            "request_fields": [
                "agent_id",
                "workspace_id",
                "session_id",
                "query",
                "mode",
                "limit",
                "scope",
            ],
            "trace_id": "trace_search",
        }
    ]


@pytest.mark.parametrize("status_code", [403, 404, 500])
def test_non_2xx_responses_raise_safe_benchmark_error(status_code: int) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={"ok": False, "message": "Memory scope is not available.", "trace_id": "trace_scope"},
        )

    adapter = MemWingAdapter(_config(), transport=httpx.MockTransport(handler))

    with pytest.raises(BenchmarkError) as exc_info:
        adapter.memory_search_details("demo scope", limit=5)

    message = str(exc_info.value)
    assert "Memory scope is not available." in message
    assert f"endpoint={SEARCH_MEMORY_ENDPOINT}" in message
    assert f"status_code={status_code}" in message
    assert "trace_id=trace_scope" in message


def test_malformed_json_response_does_not_become_empty_success() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    adapter = MemWingAdapter(_config(), transport=httpx.MockTransport(handler))

    with pytest.raises(BenchmarkError, match="not valid JSON"):
        adapter.memory_search_details("demo scope", limit=5)
    assert adapter.records == [
        {
            "method": "POST",
            "endpoint": SEARCH_MEMORY_ENDPOINT,
            "status_code": 200,
            "latency_ms": adapter.records[0]["latency_ms"],
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
    ]


def test_missing_result_shape_does_not_become_empty_success() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"trace_id": "trace_bad_shape"})

    adapter = MemWingAdapter(_config(), transport=httpx.MockTransport(handler))

    with pytest.raises(BenchmarkError, match="does not match result shape"):
        adapter.memory_search_details("demo scope", limit=5)


def test_timeout_raises_benchmark_error_with_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    adapter = MemWingAdapter(_config(), transport=httpx.MockTransport(handler))

    with pytest.raises(BenchmarkError) as exc_info:
        adapter.memory_search_details("demo scope", limit=5)

    message = str(exc_info.value)
    assert "timed out" in message
    assert f"endpoint={SEARCH_MEMORY_ENDPOINT}" in message


def _config() -> MemWingConfig:
    return MemWingConfig(
        base_url="http://memwing.test/",
        agent_id="main",
        workspace_id="workspace_001",
        session_id="memwing-benchmark",
        project_memory_space_id="project_001",
        group_id="benchmark_group",
        thread_id="benchmark_thread",
    )
