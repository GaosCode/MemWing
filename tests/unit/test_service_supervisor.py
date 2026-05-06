from __future__ import annotations

from memwing.profiles import build_profile_config
from memwing.service_supervisor import verify_profile_services


def test_full_local_service_supervisor_verifies_configured_dependencies() -> None:
    report = verify_profile_services(build_profile_config("full-local"), env={})

    assert report.ok
    assert [check.name for check in report.checks] == ["postgres", "qdrant", "neo4j"]
    assert all(check.status == "ok" for check in report.checks)


def test_service_supervisor_reports_missing_full_local_dependency_config() -> None:
    config = build_profile_config("full-local")
    del config["database"]["url"]

    report = verify_profile_services(config, env={})

    assert not report.ok
    assert report.checks[0].name == "postgres"
    assert report.checks[0].status == "fail"
