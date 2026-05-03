from types import SimpleNamespace

import pytest

from memwing_benchmark.adapters.openclaw_native import MemorySearchDetails
from memwing_benchmark.cli import _memwing_pipeline_run_config, _run_memwing_retrieval_batch
from memwing_benchmark.errors import BenchmarkError
from memwing_benchmark.schema import BenchmarkCase, Probe, SeedMessage


def test_pg_preseed_per_case_orchestrates_real_ingest_without_pg_seed(monkeypatch) -> None:
    def fail_pg_seed(**_kwargs):
        raise AssertionError("direct PG preseed must not run")

    monkeypatch.setattr("memwing_benchmark.seed_pg.run_pg_seed", fail_pg_seed)
    adapter = RecordingAdapter()
    raw_records = {
        "pg_preseed": [],
        "memwing_ingest": [],
        "memwing_pipeline_drains": [],
        "memwing_readiness": [],
        "memory_searches": [],
        "debug": [],
        "side_effects": [],
    }

    results = _run_memwing_retrieval_batch(
        run_id="run_001",
        backend="memwing-openclaw-plugin",
        cases=[_case()],
        adapter=adapter,
        judge=None,
        raw_records=raw_records,
        poll_interval_seconds=0.01,
        timeout_seconds=0,
        yes=True,
        ingest_seed_events=False,
        config=SimpleNamespace(),
        pg_preseed_per_case=True,
    )

    assert [call[0] for call in adapter.calls] == [
        "cleanup_benchmark_scope",
        "ingest_seed_messages",
        "drain_benchmark_pipeline",
        "wait_benchmark_readiness",
        "memory_search_details",
    ]
    assert results[0].case_id == "bs001"
    assert raw_records["pg_preseed"] == []
    assert raw_records["memwing_ingest"]
    assert raw_records["memwing_pipeline_drains"]
    assert raw_records["memwing_readiness"]
    assert raw_records["memory_searches"][0]["mode"] == "memwing_real_ingest_retrieval"
    assert results[0].retrieval_source_mix == {"evidence_index": 1}
    assert results[0].memory_search_warnings == [
        {"branch": "graph_backend", "reason_code": "timeout"}
    ]
    assert results[0].readiness_summary["final"]["ready"] is True


def test_real_ingest_run_config_records_backend_semantics() -> None:
    assert _memwing_pipeline_run_config(pg_preseed_per_case=True) == {
        "memory_pipeline": "real_ingest_per_case",
        "graph_backend": "graphiti",
        "evidence_backend": "qdrant",
    }
    assert _memwing_pipeline_run_config(pg_preseed_per_case=False) == {}


def test_real_ingest_pipeline_fails_when_readiness_times_out() -> None:
    adapter = RecordingAdapter(ready=False)
    raw_records = {
        "pg_preseed": [],
        "memwing_ingest": [],
        "memwing_pipeline_drains": [],
        "memwing_readiness": [],
        "memory_searches": [],
        "debug": [],
        "side_effects": [],
    }

    with pytest.raises(BenchmarkError, match="readiness timed out"):
        _run_memwing_retrieval_batch(
            run_id="run_001",
            backend="memwing-openclaw-plugin",
            cases=[_case()],
            adapter=adapter,
            judge=None,
            raw_records=raw_records,
            poll_interval_seconds=0.01,
            timeout_seconds=0,
            yes=True,
            ingest_seed_events=False,
            config=SimpleNamespace(),
            pg_preseed_per_case=True,
        )

    assert [call[0] for call in adapter.calls] == [
        "cleanup_benchmark_scope",
        "ingest_seed_messages",
        "drain_benchmark_pipeline",
        "wait_benchmark_readiness",
    ]


class RecordingAdapter:
    config = SimpleNamespace(shared_group_id="")

    def __init__(self, *, ready: bool = True) -> None:
        self.ready = ready
        self.calls: list[tuple[object, ...]] = []

    def cleanup_benchmark_scope(self, scope):
        self.calls.append(("cleanup_benchmark_scope", scope.project_memory_space_id))
        return {"trace_id": "trace_cleanup"}

    def ingest_seed_messages(self, *, case, run_id, scope):
        self.calls.append(
            ("ingest_seed_messages", case.case_id, run_id, scope.project_memory_space_id)
        )
        return [
            {
                "case_id": case.case_id,
                "seed_message_id": message.id,
                "accepted": True,
                "source_event_id": f"source_event:{message.id}",
                "trace_id": "trace_ingest",
                "latency_ms": 1,
            }
            for message in case.seed_messages
        ]

    def drain_benchmark_pipeline(self, scope, *, outbox_job_types=None):
        self.calls.append(
            (
                "drain_benchmark_pipeline",
                scope.project_memory_space_id,
                tuple(outbox_job_types or ()),
            )
        )
        return {"pending": {"outbox_jobs": 0, "graph_write_jobs": 0}}

    def wait_benchmark_readiness(
        self,
        *,
        case,
        scope,
        expected_source_event_ids,
        ignored_outbox_job_types=None,
    ):
        self.calls.append(
            (
                "wait_benchmark_readiness",
                case.case_id,
                scope.project_memory_space_id,
                tuple(expected_source_event_ids),
                tuple(ignored_outbox_job_types or ()),
            )
        )
        return {
            "case_id": case.case_id,
            "ready": self.ready,
            "attempts": [{"ready": self.ready}],
            "final": {"ready": self.ready},
        }

    def memory_search_details(self, query, *, max_results, scope):
        self.calls.append(("memory_search_details", query, scope.project_memory_space_id))
        return MemorySearchDetails(
            contexts=["云帆看板改造项目负责人确定为沈南。"],
            results=[
                {
                    "rank": 1,
                    "source": "evidence_index",
                    "snippet": "云帆看板改造项目负责人确定为沈南。",
                    "source_event_ids": ["source_event:bs001_s1"],
                }
            ],
            latency_ms=5,
            raw={"results": [], "warnings": [{"branch": "graph_backend", "reason_code": "timeout"}]},
        )


def _case() -> BenchmarkCase:
    return BenchmarkCase(
        case_id="bs001",
        category="basic",
        seed_messages=[SeedMessage(id="bs001_s1", content="负责人是沈南。")],
        probes=[
            Probe(
                id="bs001_p1",
                question="云帆负责人是谁？",
                gold_answer="沈南",
                gold_evidence_ids=["bs001_s1"],
            )
        ],
    )
