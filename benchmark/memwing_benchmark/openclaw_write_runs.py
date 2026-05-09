from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from memwing_benchmark.adapters.openclaw_native import OpenClawNativeAdapter
from memwing_benchmark.evaluation import (
    _evaluate_write,
    _expected_memories,
    _expected_memories_for_other_cases,
    _noise_memories,
    _result_from_write,
    _result_from_write_ingest,
)
from memwing_benchmark.evaluators.llm_judge import LlmJudge
from memwing_benchmark.live_workspace import LiveChatIds
from memwing_benchmark.openclaw_feishu import _new_feishu_cli
from memwing_benchmark.openclaw_idempotency import make_idempotency_key
from memwing_benchmark.openclaw_memory_artifacts import (
    _memory_artifact_contexts,
    _poll_memory_artifact_change,
    _snapshot_as_changed_files,
    _snapshot_memory_artifacts,
    _snapshot_raw,
)
from memwing_benchmark.run_support import debug as _debug
from memwing_benchmark.run_support import required_feishu_scopes as _required_feishu_scopes
from memwing_benchmark.schema import BenchmarkCase, NormalizedResult, utc_now_iso


def _run_write_live_batch(
    *,
    run_id: str,
    backend: str,
    cases: list[BenchmarkCase],
    config,
    adapter: OpenClawNativeAdapter,
    chats: LiveChatIds,
    judge: LlmJudge,
    raw_records: dict[str, Any],
    message_interval_seconds: float,
    settle_seconds: float,
    memory_poll_interval_seconds: float,
    memory_timeout_seconds: float,
) -> list[NormalizedResult]:
    _debug(raw_records, "检查 Feishu CLI 发送消息权限")
    feishu = _new_feishu_cli(config.feishu.cli_bin)
    feishu.ensure_ready(required_scopes=_required_feishu_scopes(will_create_chat=False))
    workspace = Path(adapter.get_default_workspace()).expanduser()
    seed_chat_id = chats.seed_chat_id
    results: list[NormalizedResult] = []
    for case in cases:
        _debug(
            raw_records,
            "开始 write case",
            case_id=case.case_id,
            seed_chat_id=seed_chat_id,
            workspace=str(workspace),
        )
        before = _snapshot_memory_artifacts(workspace)
        seed_completed_at: str | None = None
        for message in case.seed_messages:
            _debug(
                raw_records,
                "发送 write seed 消息",
                case_id=case.case_id,
                seed_message_id=message.id,
                chat_id=seed_chat_id,
            )
            sent_seed = feishu.send_text(
                chat_id=seed_chat_id,
                text=message.content,
                idempotency_key=make_idempotency_key(
                    run_id=run_id,
                    backend=backend,
                    case_id=case.case_id,
                    item_id=f"write_{message.id}",
                ),
            )
            raw_records["feishu"].append(
                {
                    "kind": "write_seed",
                    "case_id": case.case_id,
                    "seed_message_id": message.id,
                    "chat_id": seed_chat_id,
                    "result": sent_seed,
                }
            )
            seed_completed_at = utc_now_iso()
            if message_interval_seconds > 0:
                time.sleep(message_interval_seconds)
        if settle_seconds > 0:
            _debug(raw_records, "等待 write seed settle", case_id=case.case_id, seconds=settle_seconds)
            time.sleep(settle_seconds)
        poll_result = _poll_memory_artifact_change(
            workspace=workspace,
            before=before,
            poll_interval_seconds=memory_poll_interval_seconds,
            timeout_seconds=memory_timeout_seconds,
        )
        written_contexts = [
            change["added_text"]
            for change in poll_result.changed_files
            if isinstance(change.get("added_text"), str) and change["added_text"].strip()
        ]
        write_result = _evaluate_write(
            judge=judge,
            case_id=case.case_id,
            expected_memories=_expected_memories(case),
            noise_memories=_noise_memories(case),
            written_contexts=written_contexts,
        )
        raw_records.setdefault("memory_writes", []).append(
            {
                "case_id": case.case_id,
                "workspace": str(workspace),
                "before": _snapshot_raw(poll_result.before),
                "after": _snapshot_raw(poll_result.after),
                "changed_files": poll_result.changed_files,
                "first_changed_at": poll_result.first_changed_at,
                "timeout": poll_result.timeout,
                "write_judge": write_result.model_dump(mode="json") if write_result else None,
            }
        )
        results.append(
            _result_from_write(
                run_id=run_id,
                backend=backend,
                case=case,
                chat_id=seed_chat_id,
                seed_message_ids=[message.id for message in case.seed_messages],
                written_contexts=written_contexts,
                changed_files=poll_result.changed_files,
                seed_completed_at=seed_completed_at,
                first_changed_at=poll_result.first_changed_at,
                timeout=poll_result.timeout,
                write_result=write_result,
            )
        )
    raw_records["feishu_commands"].extend(
        command.model_dump(mode="json") for command in feishu.commands
    )
    return results

def _run_write_ingest_batch(
    *,
    run_id: str,
    backend: str,
    cases: list[BenchmarkCase],
    config,
    adapter: OpenClawNativeAdapter,
    chats: LiveChatIds,
    raw_records: dict[str, Any],
    message_interval_seconds: float,
) -> list[NormalizedResult]:
    _debug(raw_records, "检查 Feishu CLI 发送消息权限")
    feishu = _new_feishu_cli(config.feishu.cli_bin)
    feishu.ensure_ready(required_scopes=_required_feishu_scopes(will_create_chat=False))
    workspace = Path(adapter.get_default_workspace()).expanduser()
    chat_id = chats.seed_chat_id
    sent_by_case: dict[str, list[str]] = {case.case_id: [] for case in cases}
    completed_by_case: dict[str, str | None] = {case.case_id: None for case in cases}
    _debug(
        raw_records,
        "开始 write ingest batch",
        case_count=len(cases),
        chat_id=chat_id,
        workspace=str(workspace),
    )
    for case in cases:
        for message in case.seed_messages:
            _debug(
                raw_records,
                "发送 write ingest seed 消息",
                case_id=case.case_id,
                seed_message_id=message.id,
                chat_id=chat_id,
            )
            sent_seed = feishu.send_text(
                chat_id=chat_id,
                text=message.content,
                idempotency_key=make_idempotency_key(
                    run_id=run_id,
                    backend=backend,
                    case_id=case.case_id,
                    item_id=f"ingest_{message.id}",
                ),
            )
            raw_records["feishu"].append(
                {
                    "kind": "write_ingest_seed",
                    "case_id": case.case_id,
                    "seed_message_id": message.id,
                    "chat_id": chat_id,
                    "result": sent_seed,
                }
            )
            sent_by_case[case.case_id].append(message.id)
            completed_by_case[case.case_id] = utc_now_iso()
            if message_interval_seconds > 0:
                time.sleep(message_interval_seconds)
    raw_records.setdefault("memory_writes", []).append(
        {
            "phase": "ingest",
            "workspace": str(workspace),
            "chat_id": chat_id,
            "case_ids": [case.case_id for case in cases],
            "sent_message_count": sum(len(ids) for ids in sent_by_case.values()),
            "note": "ingest phase only sends seed messages; run --mode write --phase evaluate later.",
        }
    )
    raw_records["feishu_commands"].extend(
        command.model_dump(mode="json") for command in feishu.commands
    )
    return [
        _result_from_write_ingest(
            run_id=run_id,
            backend=backend,
            case=case,
            chat_id=chat_id,
            seed_message_ids=sent_by_case[case.case_id],
            seed_completed_at=completed_by_case[case.case_id],
        )
        for case in cases
    ]

def _run_write_evaluate_batch(
    *,
    run_id: str,
    backend: str,
    cases: list[BenchmarkCase],
    adapter: OpenClawNativeAdapter,
    judge: LlmJudge | None,
    raw_records: dict[str, Any],
    chat_id: str | None,
) -> list[NormalizedResult]:
    workspace = Path(adapter.get_default_workspace()).expanduser()
    _debug(
        raw_records,
        "开始 write evaluate batch",
        case_count=len(cases),
        workspace=str(workspace),
    )
    snapshot = _snapshot_memory_artifacts(workspace)
    written_contexts = _memory_artifact_contexts(snapshot)
    evaluated_files = _snapshot_as_changed_files(snapshot)
    _debug(
        raw_records,
        "write evaluate workspace snapshot 完成",
        file_count=len(snapshot.files),
        non_empty_file_count=len(written_contexts),
        total_bytes=sum(len(text.encode("utf-8")) for text in snapshot.files.values()),
        evaluated_file_count=len(evaluated_files),
        files=[
            {
                "path": path,
                "bytes": len(text.encode("utf-8")),
                "lines": len(text.splitlines()),
            }
            for path, text in sorted(snapshot.files.items())
        ],
    )
    results: list[NormalizedResult] = []
    total_cases = len(cases)
    for index, case in enumerate(cases, start=1):
        expected_memories = _expected_memories(case)
        noise_memories = _noise_memories(case)
        allowed_other_memories = _expected_memories_for_other_cases(cases, case.case_id)
        _debug(
            raw_records,
            "write evaluate case 开始",
            case_id=case.case_id,
            case_index=index,
            case_count=total_cases,
            expected_memory_count=len(expected_memories),
            noise_memory_count=len(noise_memories),
            allowed_other_memory_count=len(allowed_other_memories),
            written_context_count=len(written_contexts),
            written_context_bytes=sum(
                len(context.encode("utf-8")) for context in written_contexts
            ),
        )
        judge_started = time.monotonic()
        _debug(raw_records, "write evaluate judge 开始", case_id=case.case_id)
        write_result = _evaluate_write(
            judge=judge,
            case_id=case.case_id,
            expected_memories=expected_memories,
            noise_memories=noise_memories,
            written_contexts=written_contexts,
            allowed_other_memories=allowed_other_memories,
        )
        _debug(
            raw_records,
            "write evaluate judge 完成",
            case_id=case.case_id,
            duration_ms=round((time.monotonic() - judge_started) * 1000),
            judge_available=write_result is not None,
            write_recall=write_result.write.write_recall if write_result else None,
            write_precision=write_result.write.write_precision if write_result else None,
        )
        raw_records.setdefault("memory_writes", []).append(
            {
                "phase": "evaluate",
                "case_id": case.case_id,
                "workspace": str(workspace),
                "snapshot": _snapshot_raw(snapshot),
                "evaluated_files": evaluated_files,
                "write_judge": write_result.model_dump(mode="json") if write_result else None,
            }
        )
        results.append(
            _result_from_write(
                run_id=run_id,
                backend=backend,
                case=case,
                chat_id=chat_id,
                seed_message_ids=[message.id for message in case.seed_messages],
                written_contexts=written_contexts,
                changed_files=evaluated_files,
                seed_completed_at=None,
                first_changed_at=snapshot.captured_at if written_contexts else None,
                timeout=False,
                write_result=write_result,
                phase="evaluate",
            )
        )
    return results
