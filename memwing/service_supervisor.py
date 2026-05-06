from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import socket
from typing import Any
from urllib.parse import urlparse

from memwing.runtime_env import build_runtime_env


TcpConnect = Callable[[str, int, float], None]


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
    tcp_connect: TcpConnect | None = None,
    timeout_seconds: float = 1.0,
) -> ServiceReport:
    runtime = build_runtime_env(config, base_env=env)
    if runtime.profile != "full-local":
        return ServiceReport(
            profile=runtime.profile,
            checks=(ServiceCheck("services", "skip", f"{runtime.profile} does not provision local services"),),
        )

    connector = tcp_connect or _tcp_connect
    checks = (
        _reachable(
            "postgres",
            runtime.env.get("DATABASE_URL"),
            "database.url",
            default_port=5432,
            tcp_connect=connector,
            timeout_seconds=timeout_seconds,
        ),
        _reachable(
            "qdrant",
            runtime.env.get("MEMWING_QDRANT_URL"),
            "evidence.qdrant.url",
            default_port=6333,
            tcp_connect=connector,
            timeout_seconds=timeout_seconds,
        ),
        _reachable(
            "neo4j",
            runtime.env.get("MEMWING_GRAPHITI_NEO4J_URI"),
            "graph.neo4j.uri",
            default_port=7687,
            tcp_connect=connector,
            timeout_seconds=timeout_seconds,
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


def _reachable(
    name: str,
    value: str | None,
    config_key: str,
    *,
    default_port: int,
    tcp_connect: TcpConnect,
    timeout_seconds: float,
) -> ServiceCheck:
    if not value:
        return ServiceCheck(name, "fail", f"{config_key} is required")
    endpoint = _endpoint(value, default_port=default_port)
    if endpoint is None:
        return ServiceCheck(name, "fail", f"{config_key} must include a host")
    host, port = endpoint
    try:
        tcp_connect(host, port, timeout_seconds)
    except OSError as exc:
        return ServiceCheck(
            name,
            "fail",
            f"{config_key} is not reachable at {host}:{port}: {exc}",
        )
    return ServiceCheck(name, "ok", f"{config_key} is reachable at {host}:{port}")


def _endpoint(value: str, *, default_port: int) -> tuple[str, int] | None:
    parsed = urlparse(value)
    host = parsed.hostname
    if host is None and "://" not in value:
        parsed = urlparse(f"//{value}")
        host = parsed.hostname
    if host is None:
        return None
    try:
        port = parsed.port or default_port
    except ValueError:
        return None
    return host, port


def _tcp_connect(host: str, port: int, timeout_seconds: float) -> None:
    with socket.create_connection((host, port), timeout=timeout_seconds):
        return
