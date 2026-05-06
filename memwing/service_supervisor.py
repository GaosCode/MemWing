from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import socket
from typing import Any
from urllib.parse import urlparse

from memwing.runtime_env import build_runtime_env


TcpConnect = Callable[[str, int, float], None]
PostgresProbe = Callable[[str, float], None]
Neo4jProbe = Callable[[str, str, str, float], None]


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
    postgres_probe: PostgresProbe | None = None,
    neo4j_probe: Neo4jProbe | None = None,
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
        _postgres_ready(
            "postgres",
            runtime.env.get("DATABASE_URL"),
            "database.url",
            default_port=5432,
            tcp_connect=connector,
            postgres_probe=postgres_probe or _postgres_probe,
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
        _neo4j_ready(
            "neo4j",
            runtime.env.get("MEMWING_GRAPHITI_NEO4J_URI"),
            runtime.env.get("MEMWING_GRAPHITI_NEO4J_USER"),
            runtime.env.get("MEMWING_GRAPHITI_NEO4J_PASSWORD"),
            "graph.neo4j.uri",
            default_port=7687,
            tcp_connect=connector,
            neo4j_probe=neo4j_probe or _neo4j_probe,
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


def _postgres_ready(
    name: str,
    value: str | None,
    config_key: str,
    *,
    default_port: int,
    tcp_connect: TcpConnect,
    postgres_probe: PostgresProbe,
    timeout_seconds: float,
) -> ServiceCheck:
    reachable = _reachable(
        name,
        value,
        config_key,
        default_port=default_port,
        tcp_connect=tcp_connect,
        timeout_seconds=timeout_seconds,
    )
    if reachable.status == "fail" or not value:
        return reachable
    endpoint = _endpoint(value, default_port=default_port)
    assert endpoint is not None
    host, port = endpoint
    try:
        postgres_probe(value, timeout_seconds)
    except Exception as exc:  # noqa: BLE001
        return ServiceCheck(
            name,
            "fail",
            f"{config_key} authentication failed at {host}:{port}: {_first_error_line(exc)}",
        )
    return ServiceCheck(name, "ok", f"{config_key} authenticated at {host}:{port}")


def _neo4j_ready(
    name: str,
    uri: str | None,
    user: str | None,
    password: str | None,
    config_key: str,
    *,
    default_port: int,
    tcp_connect: TcpConnect,
    neo4j_probe: Neo4jProbe,
    timeout_seconds: float,
) -> ServiceCheck:
    if not user:
        return ServiceCheck(name, "fail", "graph.neo4j.user is required")
    reachable = _reachable(
        name,
        uri,
        config_key,
        default_port=default_port,
        tcp_connect=tcp_connect,
        timeout_seconds=timeout_seconds,
    )
    if reachable.status == "fail" or not uri:
        return reachable
    endpoint = _endpoint(uri, default_port=default_port)
    assert endpoint is not None
    host, port = endpoint
    if not password:
        return ServiceCheck(
            name,
            "fail",
            "graph.neo4j.password is required for full-local Graphiti/Neo4j",
        )
    try:
        neo4j_probe(uri, user, password, timeout_seconds)
    except Exception as exc:  # noqa: BLE001
        return ServiceCheck(
            name,
            "fail",
            f"graph.neo4j authentication failed at {host}:{port}: {_first_error_line(exc)}",
        )
    return ServiceCheck(name, "ok", f"{config_key} authenticated at {host}:{port}")


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


def _postgres_probe(database_url: str, timeout_seconds: float) -> None:
    import psycopg

    connect_timeout = max(1, int(timeout_seconds))
    with psycopg.connect(database_url, connect_timeout=connect_timeout) as connection:
        with connection.cursor() as cursor:
            cursor.execute("select 1")
            cursor.fetchone()


def _neo4j_probe(uri: str, user: str, password: str, timeout_seconds: float) -> None:
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(
        uri,
        auth=(user, password),
        connection_timeout=timeout_seconds,
    )
    try:
        driver.verify_connectivity()
    finally:
        driver.close()


def _first_error_line(exc: Exception) -> str:
    text = str(exc).strip().splitlines()
    return text[0] if text else exc.__class__.__name__
