from __future__ import annotations

from typing import Any

from memwing_benchmark.adapters.memwing import MemWingAdapter
from memwing_benchmark.adapters.openclaw_native import OpenClawNativeAdapter
from memwing_benchmark.errors import BenchmarkError
from memwing_benchmark.run_records import _record_memwing_http_records
from memwing_benchmark.run_support import debug as _debug


OPENCLAW_NATIVE_BACKEND = "openclaw-native"
MEMWING_LEGACY_BACKEND = "memwing"
MEMWING_HTTP_BACKEND = "memwing-http"
MEMWING_OPENCLAW_PLUGIN_BACKEND = "memwing-openclaw-plugin"
SUPPORTED_BACKENDS = {
    OPENCLAW_NATIVE_BACKEND,
    MEMWING_LEGACY_BACKEND,
    MEMWING_HTTP_BACKEND,
    MEMWING_OPENCLAW_PLUGIN_BACKEND,
}
MEMWING_PLUGIN_BASE_URL_CONFIG_PATH = "plugins.entries.memwing.config.memwingBaseUrl"
MEMWING_PLUGIN_ENABLED_CONFIG_PATH = "plugins.entries.memwing.enabled"
MEMWING_PLUGIN_CONVERSATION_ACCESS_CONFIG_PATH = (
    "plugins.entries.memwing.hooks.allowConversationAccess"
)
MEMWING_WRITE_EVALUATE_MIN_PIPELINE_TIMEOUT_SECONDS = 1200.0


def _validate_run_options(
    *,
    backend: str,
    mode: str,
    phase: str,
    ingest_run_id: str | None,
    live: bool,
    batch: bool,
    memory_poll_interval_seconds: float,
    memory_timeout_seconds: float,
    pg_preseed_per_case: bool,
    preseed_expected: bool,
    preseed_graph_mode: str,
) -> tuple[str, str | None]:
    if backend not in SUPPORTED_BACKENDS:
        raise BenchmarkError(
            "--backend must be one of: openclaw-native, memwing-http, memwing-openclaw-plugin"
        )
    backend = _canonical_backend(backend)
    if mode not in {"retrieval", "write"}:
        raise BenchmarkError("--mode must be one of: retrieval, write")
    if phase not in {"full", "ingest", "evaluate"}:
        raise BenchmarkError("--phase must be one of: full, ingest, evaluate")
    if mode != "write" and phase != "full":
        raise BenchmarkError("--phase is only supported with --mode write")
    if ingest_run_id is not None:
        ingest_run_id = ingest_run_id.strip()
        if not ingest_run_id:
            raise BenchmarkError("--ingest-run-id must not be empty")
    if ingest_run_id and not (mode == "write" and phase == "evaluate"):
        raise BenchmarkError("--ingest-run-id is only supported with --mode write --phase evaluate")
    if ingest_run_id and backend not in {MEMWING_HTTP_BACKEND, MEMWING_OPENCLAW_PLUGIN_BACKEND}:
        raise BenchmarkError("--ingest-run-id is only supported with MemWing write evaluate backends")
    if mode == "retrieval" and live and batch:
        raise BenchmarkError("--mode retrieval --live currently supports a single case only")
    if (
        backend == OPENCLAW_NATIVE_BACKEND
        and mode == "write"
        and phase in {"full", "ingest"}
        and not live
    ):
        raise BenchmarkError("--mode write --phase full/ingest requires --live")
    if backend == OPENCLAW_NATIVE_BACKEND and mode == "write" and phase == "evaluate" and live:
        raise BenchmarkError("--mode write --phase evaluate reads local memory files; omit --live")
    if memory_poll_interval_seconds <= 0:
        raise BenchmarkError("--memory-poll-interval-seconds must be greater than 0")
    if memory_timeout_seconds < 0:
        raise BenchmarkError("--memory-timeout-seconds must be greater than or equal to 0")
    if pg_preseed_per_case and mode != "retrieval":
        raise BenchmarkError("--pg-preseed-per-case is only supported with --mode retrieval")
    if preseed_expected and mode != "retrieval":
        raise BenchmarkError("--preseed-expected is only supported with --mode retrieval")
    if preseed_expected and pg_preseed_per_case:
        raise BenchmarkError("--preseed-expected cannot be combined with --pg-preseed-per-case")
    if preseed_graph_mode not in {"direct_neo4j", "graphiti"}:
        raise BenchmarkError("--preseed-graph-mode must be direct_neo4j or graphiti")
    if pg_preseed_per_case and backend not in {
        MEMWING_HTTP_BACKEND,
        MEMWING_OPENCLAW_PLUGIN_BACKEND,
    }:
        raise BenchmarkError(
            "--pg-preseed-per-case is only supported with --backend memwing-http or "
            "--backend memwing-openclaw-plugin"
        )
    if preseed_expected and backend not in {
        MEMWING_HTTP_BACKEND,
        MEMWING_OPENCLAW_PLUGIN_BACKEND,
    }:
        raise BenchmarkError(
            "--preseed-expected is only supported with --backend memwing-http or "
            "--backend memwing-openclaw-plugin"
        )
    return backend, ingest_run_id

def _with_memwing_write_evaluate_pipeline_timeout(
    config: Any,
    *,
    backend: str,
    mode: str,
    phase: str,
) -> Any:
    if backend not in {MEMWING_HTTP_BACKEND, MEMWING_OPENCLAW_PLUGIN_BACKEND}:
        return config
    if mode != "write" or phase not in {"full", "evaluate"}:
        return config
    if config.memwing.poll_timeout_seconds >= MEMWING_WRITE_EVALUATE_MIN_PIPELINE_TIMEOUT_SECONDS:
        return config
    memwing_config = config.memwing.model_copy(
        update={
            "poll_timeout_seconds": MEMWING_WRITE_EVALUATE_MIN_PIPELINE_TIMEOUT_SECONDS,
        }
    )
    return config.model_copy(update={"memwing": memwing_config})

def _canonical_backend(backend: str) -> str:
    if backend == MEMWING_LEGACY_BACKEND:
        return MEMWING_HTTP_BACKEND
    return backend

def _preflight_memwing_http(*, adapter: MemWingAdapter, raw_records: dict[str, Any]) -> None:
    health = getattr(adapter, "health", None)
    if callable(health):
        _debug(raw_records, "检查 MemWing HTTP readiness")
        health()
        _record_memwing_http_records(raw_records, adapter.records)

def _preflight_memwing_openclaw_plugin(
    *,
    config,
    adapter: OpenClawNativeAdapter,
    raw_records: dict[str, Any],
) -> None:
    _debug(raw_records, "检查 OpenClaw MemWing plugin 配置")
    enabled = adapter.get_config_value(MEMWING_PLUGIN_ENABLED_CONFIG_PATH)
    conversation_access = adapter.get_config_value(MEMWING_PLUGIN_CONVERSATION_ACCESS_CONFIG_PATH)
    base_url = adapter.get_config_value(MEMWING_PLUGIN_BASE_URL_CONFIG_PATH)
    raw_records.setdefault("openclaw_plugin_preflight", []).append(
        {
            "plugin_id": "memwing",
            "enabled_present": enabled.present,
            "enabled": enabled.value if isinstance(enabled.value, bool) else None,
            "conversation_access_present": conversation_access.present,
            "conversation_access": conversation_access.value
            if isinstance(conversation_access.value, bool)
            else None,
            "base_url_present": base_url.present,
            "base_url_matches_memwing": (
                _normalized_url(str(base_url.value)) == config.memwing.normalized_base_url
                if isinstance(base_url.value, str)
                else False
            ),
        }
    )
    if enabled.value is not True:
        raise BenchmarkError("OpenClaw MemWing plugin must be enabled")
    if conversation_access.value is not True:
        raise BenchmarkError(
            "OpenClaw MemWing plugin must enable hooks.allowConversationAccess"
        )
    if not isinstance(base_url.value, str) or not base_url.value.strip():
        raise BenchmarkError("OpenClaw MemWing plugin config memwingBaseUrl is required")
    if _normalized_url(base_url.value) != config.memwing.normalized_base_url:
        raise BenchmarkError("OpenClaw MemWing plugin config does not match memwing.base_url")

def _normalized_url(value: str) -> str:
    return value.strip().rstrip("/")
