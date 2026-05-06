from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from memwing.runtime_env import build_runtime_env


@dataclass(frozen=True, slots=True)
class ServiceCheck:
    name: str
    status: str
    message: str


@dataclass(frozen=True, slots=True)
class ServiceReport:
    profile: str
    checks: tuple[ServiceCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.status != "fail" for check in self.checks)


def verify_profile_services(
    config: Mapping[str, Any],
    *,
    env: Mapping[str, str] | None = None,
) -> ServiceReport:
    runtime = build_runtime_env(config, base_env=env)
    if runtime.profile != "full-local":
        return ServiceReport(
            profile=runtime.profile,
            checks=(ServiceCheck("services", "skip", f"{runtime.profile} does not provision local services"),),
        )

    checks = (
        _required("postgres", runtime.env.get("DATABASE_URL"), "database.url"),
        _required("qdrant", runtime.env.get("MEMWING_QDRANT_URL"), "evidence.qdrant.url"),
        _required(
            "neo4j",
            runtime.env.get("MEMWING_GRAPHITI_NEO4J_URI"),
            "graph.neo4j.uri",
        ),
    )
    return ServiceReport(profile=runtime.profile, checks=checks)


def render_service_report(report: ServiceReport) -> str:
    lines = [f"profile: {report.profile}"]
    for check in report.checks:
        lines.append(f"{check.status}: {check.name}: {check.message}")
    return "\n".join(lines)


def _required(name: str, value: str | None, config_key: str) -> ServiceCheck:
    if not value:
        return ServiceCheck(name, "fail", f"{config_key} is required")
    return ServiceCheck(name, "ok", f"{config_key} is configured")
