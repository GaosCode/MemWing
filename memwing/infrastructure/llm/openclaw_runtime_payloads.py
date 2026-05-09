from __future__ import annotations

from collections.abc import Mapping
import json
import math
import re

from memwing.infrastructure.llm.errors import LLMOutputSchemaError
from memwing.infrastructure.llm.model_client import LLMModelRequest
from memwing.infrastructure.llm.openclaw_runtime_transport import OpenClawCommandResult


def command_failure_message(label: str, result: OpenClawCommandResult) -> str:
    parts = [f"OpenClaw runtime {label} failed with exit code {result.returncode}"]
    stderr_summary = safe_process_output_summary(result.stderr)
    if stderr_summary:
        parts.append(f"stderr={stderr_summary}")
    elif result.stderr:
        parts.append(f"stderr_len={len(result.stderr)}")
    if result.stdout:
        stdout_summary = safe_process_output_summary(result.stdout)
        if stdout_summary:
            parts.append(f"stdout_summary={stdout_summary}")
        parts.append(f"stdout_len={len(result.stdout)}")
    return "; ".join(parts)


def is_empty_text_output_failure(result: OpenClawCommandResult) -> bool:
    if result.returncode == 0:
        return False
    return "No text output returned" in result.stderr


def safe_process_output_summary(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    summary = " | ".join(lines[-3:])
    summary = re.sub(r"[\x00-\x1f\x7f]+", " ", summary)
    summary = re.sub(
        r"(?i)(authorization|api[_-]?key|token|password|secret)(\s*[:=]\s*)(\S+)",
        r"\1\2[redacted]",
        summary,
    )
    summary = re.sub(r"(?i)bearer\s+\S+", "Bearer [redacted]", summary)
    summary = re.sub(r"(?i)secret", "[redacted]", summary)
    if len(summary) > 500:
        return f"{summary[:500]}...[truncated]"
    return summary


def prompt_text(request: LLMModelRequest) -> str:
    system_prompt = request.system_prompt.strip()
    user_prompt = request.user_prompt.strip()
    if system_prompt:
        return f"System:\n{system_prompt}\n\nUser:\n{user_prompt}"
    return user_prompt


def parse_cli_json(stdout: str) -> Mapping[str, object]:
    stripped = stdout.strip()
    if not stripped:
        raise LLMOutputSchemaError("OpenClaw runtime returned empty output")
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = _parse_last_json_object(stripped)
    if not isinstance(parsed, dict):
        raise LLMOutputSchemaError("OpenClaw runtime output must be a JSON object")
    return parsed


def _parse_last_json_object(stdout: str) -> object:
    decoder = json.JSONDecoder()
    parsed_objects: list[object] = []
    start = 0
    while True:
        start = stdout.find("{", start)
        if start == -1:
            break
        try:
            parsed, end = decoder.raw_decode(stdout[start:])
        except json.JSONDecodeError:
            start += 1
            continue
        parsed_objects.append(parsed)
        start += end
    for parsed in reversed(parsed_objects):
        if isinstance(parsed, dict):
            return parsed
    raise LLMOutputSchemaError("OpenClaw runtime returned invalid JSON")


def output_text(payload: Mapping[str, object]) -> str:
    outputs = payload.get("outputs")
    if not isinstance(outputs, list):
        raise LLMOutputSchemaError("OpenClaw runtime output requires outputs")
    text_parts = [
        output.get("text")
        for output in outputs
        if isinstance(output, dict) and isinstance(output.get("text"), str)
    ]
    text = "".join(text_parts).strip()
    if not text:
        raise LLMOutputSchemaError("OpenClaw runtime output requires text output")
    return text


def embedding_outputs(
    payload: Mapping[str, object],
    *,
    expected_texts: tuple[str, ...],
) -> tuple[tuple[float, ...], ...]:
    outputs = payload.get("outputs")
    if not isinstance(outputs, list):
        raise LLMOutputSchemaError("OpenClaw runtime embedding output requires outputs")
    if len(outputs) != len(expected_texts):
        raise LLMOutputSchemaError("OpenClaw runtime embedding output count mismatch")

    vectors: list[tuple[float, ...]] = []
    for output, expected_text in zip(outputs, expected_texts, strict=True):
        if not isinstance(output, dict):
            raise LLMOutputSchemaError("OpenClaw runtime embedding output must be an object")
        if output.get("text") != expected_text:
            raise LLMOutputSchemaError("OpenClaw runtime embedding output text mismatch")
        embedding = output.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            raise LLMOutputSchemaError("OpenClaw runtime embedding output requires embedding")
        vectors.append(_embedding_vector(embedding))
    return tuple(vectors)


def _embedding_vector(embedding: list[object]) -> tuple[float, ...]:
    vector: list[float] = []
    for value in embedding:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise LLMOutputSchemaError("OpenClaw runtime embedding values must be numeric")
        number = float(value)
        if not math.isfinite(number):
            raise LLMOutputSchemaError("OpenClaw runtime embedding values must be finite")
        vector.append(number)
    return tuple(vector)


def optional_text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None
