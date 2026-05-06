from __future__ import annotations

from memwing.profiles import build_profile_config
from memwing.service_supervisor import verify_profile_services


def test_full_local_service_supervisor_verifies_configured_dependencies() -> None:
    seen: list[tuple[str, int]] = []

    def fake_tcp_connect(host: str, port: int, _timeout: float) -> None:
        seen.append((host, port))

    config = build_profile_config("full-local")
    config["graph"]["neo4j"]["password"] = "neo4j-password"

    report = verify_profile_services(
        config,
        env={},
        tcp_connect=fake_tcp_connect,
        postgres_probe=lambda *_args: None,
        neo4j_probe=lambda *_args: None,
    )

    assert report.ok
    assert [check.name for check in report.checks] == ["postgres", "qdrant", "neo4j"]
    assert all(check.status == "ok" for check in report.checks)
    assert seen == [
        ("127.0.0.1", 5432),
        ("127.0.0.1", 6333),
        ("127.0.0.1", 7687),
    ]


def test_service_supervisor_reports_missing_full_local_dependency_config() -> None:
    config = build_profile_config("full-local")
    del config["database"]["url"]

    report = verify_profile_services(
        config,
        env={},
        tcp_connect=lambda *_args: None,
        postgres_probe=lambda *_args: None,
        neo4j_probe=lambda *_args: None,
    )

    assert not report.ok
    assert report.checks[0].name == "postgres"
    assert report.checks[0].status == "fail"


def test_service_supervisor_fails_when_configured_dependency_is_unreachable() -> None:
    def failing_tcp_connect(_host: str, _port: int, _timeout: float) -> None:
        raise OSError("connection refused")

    report = verify_profile_services(
        build_profile_config("full-local"),
        env={},
        tcp_connect=failing_tcp_connect,
        postgres_probe=lambda *_args: None,
        neo4j_probe=lambda *_args: None,
    )

    assert not report.ok
    assert report.checks[0].name == "postgres"
    assert report.checks[0].status == "fail"
    assert "connection refused" in report.checks[0].message


def test_service_supervisor_fails_when_postgres_authentication_fails() -> None:
    def failing_postgres_probe(_database_url: str, _timeout: float) -> None:
        raise RuntimeError("no password supplied")

    report = verify_profile_services(
        build_profile_config("full-local"),
        env={},
        tcp_connect=lambda *_args: None,
        postgres_probe=failing_postgres_probe,
        neo4j_probe=lambda *_args: None,
    )

    assert not report.ok
    assert report.checks[0].name == "postgres"
    assert report.checks[0].status == "fail"
    assert "database.url authentication failed" in report.checks[0].message
    assert "no password supplied" in report.checks[0].message


def test_service_supervisor_requires_full_local_neo4j_password() -> None:
    report = verify_profile_services(
        build_profile_config("full-local"),
        env={},
        tcp_connect=lambda *_args: None,
        postgres_probe=lambda *_args: None,
        neo4j_probe=lambda *_args: None,
    )

    assert not report.ok
    assert report.checks[2].name == "neo4j"
    assert report.checks[2].status == "fail"
    assert "graph.neo4j.password is required" in report.checks[2].message


def test_service_supervisor_fails_when_neo4j_authentication_fails() -> None:
    config = build_profile_config("full-local")
    config["graph"]["neo4j"]["password"] = "wrong"

    def failing_neo4j_probe(_uri: str, _user: str, _password: str, _timeout: float) -> None:
        raise RuntimeError("unauthorized")

    report = verify_profile_services(
        config,
        env={},
        tcp_connect=lambda *_args: None,
        postgres_probe=lambda *_args: None,
        neo4j_probe=failing_neo4j_probe,
    )

    assert not report.ok
    assert report.checks[2].name == "neo4j"
    assert report.checks[2].status == "fail"
    assert "graph.neo4j authentication failed" in report.checks[2].message
    assert "unauthorized" in report.checks[2].message
