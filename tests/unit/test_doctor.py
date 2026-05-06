from __future__ import annotations

import json
from pathlib import Path

from memwing.config_store import default_config, set_config_value
from memwing.doctor import (
    build_runtime_status,
    dumps_report_json,
    render_doctor_text,
    run_doctor,
)
from memwing.openclaw_installer import OpenClawCommandResult


def test_doctor_lite_does_not_require_full_local_services(tmp_path: Path) -> None:
    config = default_config()

    report = run_doctor(
        config,
        env={"MEMWING_HOME": str(tmp_path / "home")},
        command_lookup=lambda command: f"/bin/{command}",
        openclaw_runner=_successful_openclaw_runner,
    )

    assert report.exit_code() == 0
    rendered = render_doctor_text(report)
    assert "Lite does not require Neo4j" in rendered
    assert "Lite does not require Qdrant" in rendered
    assert "database.url is required" not in rendered
    assert "ok: openclaw_plugin: plugin enabled, context engine selected, conversation hook enabled" in rendered


def test_doctor_full_local_reports_missing_database_model_and_backends() -> None:
    config = default_config()
    set_config_value(config, "profile", "full-local")
    set_config_value(config, "runtime.modelRuntime", "")
    set_config_value(config, "graph.backend", "graphiti")
    set_config_value(config, "evidence.backend", "qdrant")

    report = run_doctor(config, env={}, command_lookup=lambda _command: None)

    assert report.exit_code() == 1
    messages = {check.name: check.message for check in report.checks}
    assert messages["database"] == "database.url is required for full-local and production profiles"
    assert messages["model"] == "runtime.modelRuntime is required"
    assert messages["graph"] == (
        "graph.neo4j.uri and graph.neo4j.user are required when graph.backend=graphiti"
    )
    assert messages["evidence"] == (
        "evidence.qdrant.url is required when evidence.backend=qdrant"
    )
    assert messages["openclaw"] == "OpenClaw CLI is not available: openclaw"
    assert messages["openclaw_plugin"] == "OpenClaw CLI is not available: openclaw"


def test_status_reports_effective_runtime_config_without_health_probe(tmp_path: Path) -> None:
    config = default_config()
    set_config_value(config, "api.port", 8123)

    status = build_runtime_status(
        config,
        config_path=str(tmp_path / "memwing.json"),
        env={"MEMWING_HOME": str(tmp_path / "home")},
        check_health=False,
    )

    assert status.profile == "lite"
    assert status.api_base_url == "http://127.0.0.1:8123"
    assert status.api_health == "not checked"
    assert status.storage_backend == "sqlite"
    assert status.graph_backend == "disabled"
    assert status.evidence_backend == "disabled"
    assert status.model_runtime == "openclaw"
    assert json.loads(dumps_report_json(status))["api_base_url"] == "http://127.0.0.1:8123"


def test_status_health_probe_surfaces_unreachable_api(tmp_path: Path) -> None:
    config = default_config()

    def failing_get(_url: str, _timeout: float) -> str:
        raise OSError("connection refused")

    status = build_runtime_status(
        config,
        config_path=str(tmp_path / "memwing.json"),
        env={"MEMWING_HOME": str(tmp_path / "home")},
        http_get=failing_get,
    )

    assert status.api_health == "unreachable: connection refused"


def test_doctor_json_output_includes_fix_message() -> None:
    report = run_doctor(
        default_config(),
        env={},
        command_lookup=lambda command: f"/bin/{command}",
        openclaw_runner=_successful_openclaw_runner,
        fix=True,
    )

    payload = json.loads(dumps_report_json(report))

    assert payload["fix"] == "no automatic fixes were applied"
    assert payload["ok"] is True


def test_doctor_fails_when_openclaw_plugin_is_not_enabled(tmp_path: Path) -> None:
    report = run_doctor(
        default_config(),
        env={"MEMWING_HOME": str(tmp_path / "home")},
        command_lookup=lambda command: f"/bin/{command}",
        openclaw_runner=_disabled_openclaw_runner,
    )

    assert report.exit_code() == 1
    messages = {check.name: check.message for check in report.checks}
    assert "plugins.entries.memwing.enabled must be true" in messages["openclaw_plugin"]


def _successful_openclaw_runner(command: object) -> OpenClawCommandResult:
    argv = getattr(command, "argv")
    if argv[1:3] == ("plugins", "inspect"):
        stdout = json.dumps({"capabilities": [{"kind": "context-engine", "ids": ["memwing"]}]})
    elif argv[1:3] == ("config", "get") and argv[3] == "plugins.slots.contextEngine":
        stdout = json.dumps("memwing")
    elif argv[1:3] == ("config", "get") and argv[3] == "plugins.entries.memwing":
        stdout = json.dumps({"enabled": True, "hooks": {"allowConversationAccess": True}})
    else:
        stdout = ""
    return OpenClawCommandResult(tuple(argv), 0, stdout, "")


def _disabled_openclaw_runner(command: object) -> OpenClawCommandResult:
    argv = getattr(command, "argv")
    if argv[1:3] == ("plugins", "inspect"):
        stdout = json.dumps({"capabilities": [{"kind": "context-engine", "ids": ["memwing"]}]})
    elif argv[1:3] == ("config", "get") and argv[3] == "plugins.slots.contextEngine":
        stdout = json.dumps("memwing")
    elif argv[1:3] == ("config", "get") and argv[3] == "plugins.entries.memwing":
        stdout = json.dumps({"enabled": False, "hooks": {"allowConversationAccess": True}})
    else:
        stdout = ""
    return OpenClawCommandResult(tuple(argv), 0, stdout, "")
