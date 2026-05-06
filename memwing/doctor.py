from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import os
import shlex
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from memwing.config_store import get_config_value
from memwing.runtime_env import build_runtime_env


CheckStatus = str


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    name: str
    status: CheckStatus
    message: str


@dataclass(frozen=True, slots=True)
class DoctorReport:
    profile: str
    checks: tuple[DoctorCheck, ...]
    fix_message: str | None = None

    @property
    def ok(self) -> bool:
        return all(check.status != "fail" for check in self.checks)

    def exit_code(self) -> int:
        return 0 if self.ok else 1

    def to_json(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "profile": self.profile,
            "ok": self.ok,
            "checks": [
                {"name": check.name, "status": check.status, "message": check.message}
                for check in self.checks
            ],
        }
        if self.fix_message is not None:
            payload["fix"] = self.fix_message
        return payload


@dataclass(frozen=True, slots=True)
class RuntimeStatus:
    profile: str
    config_path: str
    api_base_url: str
    api_health: str
    storage_backend: str
    graph_backend: str
    evidence_backend: str
    model_runtime: str
    openclaw_cli: str

    def to_json(self) -> dict[str, str]:
        return {
            "profile": self.profile,
            "config_path": self.config_path,
            "api_base_url": self.api_base_url,
            "api_health": self.api_health,
            "storage_backend": self.storage_backend,
            "graph_backend": self.graph_backend,
            "evidence_backend": self.evidence_backend,
            "model_runtime": self.model_runtime,
            "openclaw_cli": self.openclaw_cli,
        }


def run_doctor(
    config: Mapping[str, Any],
    *,
    env: Mapping[str, str] | None = None,
    command_lookup: Callable[[str], str | None] | None = None,
    fix: bool = False,
) -> DoctorReport:
    runtime_env = build_runtime_env(config, base_env=env)
    checks: list[DoctorCheck] = [
        DoctorCheck("config", "ok", "MemWing config is parseable"),
        DoctorCheck("profile", "ok", f"profile={runtime_env.profile}"),
        _api_check(runtime_env.env),
        _storage_check(runtime_env.profile, runtime_env.env),
        _model_check(runtime_env.env),
        _graph_check(runtime_env.profile, runtime_env.env),
        _evidence_check(runtime_env.profile, runtime_env.env),
        _openclaw_cli_check(config, env=env, command_lookup=command_lookup),
    ]
    fix_message = "no automatic fixes were applied" if fix else None
    return DoctorReport(
        profile=runtime_env.profile,
        checks=tuple(checks),
        fix_message=fix_message,
    )


def render_doctor_text(report: DoctorReport) -> str:
    lines = [f"profile: {report.profile}"]
    for check in report.checks:
        lines.append(f"{check.status}: {check.name}: {check.message}")
    if report.fix_message is not None:
        lines.append(f"fix: {report.fix_message}")
    return "\n".join(lines)


def build_runtime_status(
    config: Mapping[str, Any],
    *,
    config_path: str,
    env: Mapping[str, str] | None = None,
    check_health: bool = True,
    http_get: Callable[[str, float], str] | None = None,
) -> RuntimeStatus:
    runtime_env = build_runtime_env(config, base_env=env)
    api_base_url = _api_base_url(runtime_env.env)
    health = "not checked"
    if check_health:
        health_checker = http_get or _http_get
        try:
            health = health_checker(f"{api_base_url}/healthz", 1.0)
        except (OSError, URLError, TimeoutError) as exc:
            health = f"unreachable: {exc}"
    return RuntimeStatus(
        profile=runtime_env.profile,
        config_path=config_path,
        api_base_url=api_base_url,
        api_health=health,
        storage_backend=runtime_env.env.get("MEMWING_STORAGE_BACKEND", "unset"),
        graph_backend=runtime_env.env.get("MEMWING_GRAPH_BACKEND", "unset"),
        evidence_backend=runtime_env.env.get("MEMWING_EVIDENCE_BACKEND", "unset"),
        model_runtime=runtime_env.env.get("MEMWING_MODEL_RUNTIME", "unset"),
        openclaw_cli=_openclaw_command(config, env=env)[0],
    )


def render_status_text(status: RuntimeStatus) -> str:
    return "\n".join(
        (
            f"profile: {status.profile}",
            f"config: {status.config_path}",
            f"api: {status.api_base_url}",
            f"api_health: {status.api_health}",
            f"storage: {status.storage_backend}",
            f"graph: {status.graph_backend}",
            f"evidence: {status.evidence_backend}",
            f"model: {status.model_runtime}",
            f"openclaw: {status.openclaw_cli}",
        )
    )


def dumps_report_json(value: DoctorReport | RuntimeStatus) -> str:
    return json.dumps(value.to_json(), ensure_ascii=False, indent=2, sort_keys=True)


def _api_check(env: Mapping[str, str]) -> DoctorCheck:
    host = env.get("MEMWING_API_HOST")
    port = env.get("MEMWING_API_PORT")
    if not host or not port:
        return DoctorCheck("api", "fail", "api.host and api.port are required")
    return DoctorCheck("api", "ok", f"API will bind {host}:{port}")


def _storage_check(profile: str, env: Mapping[str, str]) -> DoctorCheck:
    if profile == "lite":
        sqlite_path = env.get("MEMWING_LITE_DB_PATH")
        if not sqlite_path:
            return DoctorCheck("storage", "fail", "runtime.sqlitePath could not be resolved")
        return DoctorCheck("storage", "ok", f"Lite uses SQLite at {sqlite_path}")
    if not env.get("DATABASE_URL"):
        return DoctorCheck(
            "database",
            "fail",
            "database.url is required for full-local and production profiles",
        )
    return DoctorCheck("database", "ok", "database.url is configured")


def _model_check(env: Mapping[str, str]) -> DoctorCheck:
    model_runtime = env.get("MEMWING_MODEL_RUNTIME")
    if not model_runtime:
        return DoctorCheck("model", "fail", "runtime.modelRuntime is required")
    return DoctorCheck("model", "ok", f"model runtime is {model_runtime}")


def _graph_check(profile: str, env: Mapping[str, str]) -> DoctorCheck:
    backend = env.get("MEMWING_GRAPH_BACKEND", "disabled")
    if backend == "disabled":
        detail = "Lite does not require Neo4j" if profile == "lite" else "graph is disabled"
        return DoctorCheck("graph", "ok", detail)
    if backend != "graphiti":
        return DoctorCheck("graph", "fail", "graph.backend must be disabled or graphiti")
    missing = [
        name
        for name in ("MEMWING_GRAPHITI_NEO4J_URI", "MEMWING_GRAPHITI_NEO4J_USER")
        if not env.get(name)
    ]
    if missing:
        return DoctorCheck(
            "graph",
            "fail",
            "graph.neo4j.uri and graph.neo4j.user are required when graph.backend=graphiti",
        )
    if profile == "production" and not env.get("MEMWING_GRAPHITI_NEO4J_PASSWORD"):
        return DoctorCheck(
            "graph",
            "fail",
            "graph.neo4j.password is required for production Graphiti/Neo4j",
        )
    return DoctorCheck("graph", "ok", "Graphiti/Neo4j config is present")


def _evidence_check(profile: str, env: Mapping[str, str]) -> DoctorCheck:
    backend = env.get("MEMWING_EVIDENCE_BACKEND", "disabled")
    if backend == "disabled":
        detail = "Lite does not require Qdrant" if profile == "lite" else "evidence is disabled"
        return DoctorCheck("evidence", "ok", detail)
    if backend != "qdrant":
        return DoctorCheck("evidence", "fail", "evidence.backend must be disabled or qdrant")
    if not env.get("MEMWING_QDRANT_URL"):
        return DoctorCheck(
            "evidence",
            "fail",
            "evidence.qdrant.url is required when evidence.backend=qdrant",
        )
    if profile == "production" and not env.get("MEMWING_QDRANT_API_KEY"):
        return DoctorCheck(
            "evidence",
            "fail",
            "evidence.qdrant.apiKey is required for production Qdrant",
        )
    return DoctorCheck("evidence", "ok", "Qdrant config is present")


def _openclaw_cli_check(
    config: Mapping[str, Any],
    *,
    env: Mapping[str, str] | None,
    command_lookup: Callable[[str], str | None] | None,
) -> DoctorCheck:
    command, _args, _cwd = _openclaw_command(config, env=env)
    lookup = command_lookup or _which
    resolved = lookup(command)
    if resolved is None:
        return DoctorCheck("openclaw", "fail", f"OpenClaw CLI is not available: {command}")
    return DoctorCheck("openclaw", "ok", f"OpenClaw CLI found at {resolved}")


def _api_base_url(env: Mapping[str, str]) -> str:
    host = env.get("MEMWING_API_HOST", "127.0.0.1")
    if host == "0.0.0.0":
        host = "127.0.0.1"
    port = env.get("MEMWING_API_PORT", "8000")
    return f"http://{host}:{port}"


def _openclaw_command(
    config: Mapping[str, Any],
    *,
    env: Mapping[str, str] | None,
) -> tuple[str, tuple[str, ...], str | None]:
    source = os.environ if env is None else env
    command = _optional_config(config, "openclaw.cli") or source.get("OPENCLAW_CLI") or "openclaw"
    raw_args = _optional_config(config, "openclaw.cliArgs") or source.get("OPENCLAW_CLI_ARGS") or ""
    cwd = _optional_config(config, "openclaw.cwd") or source.get("OPENCLAW_CLI_CWD")
    return command, tuple(shlex.split(raw_args)), cwd


def _optional_config(config: Mapping[str, Any], dotted_key: str) -> str | None:
    try:
        value = get_config_value(config, dotted_key)
    except ValueError:
        return None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _which(command: str) -> str | None:
    from shutil import which

    return which(command)


def _http_get(url: str, timeout: float) -> str:
    with urlopen(url, timeout=timeout) as response:
        body = response.read().decode("utf-8")
        return body.strip() or f"HTTP {response.status}"
