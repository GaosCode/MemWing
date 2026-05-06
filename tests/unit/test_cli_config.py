from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from memwing.cli import main
from memwing.config_store import load_json_config
from memwing.cli import RuntimeLaunch
from memwing.service_supervisor import ServiceCheck, ServiceReport


def test_memwing_config_set_get_unset_and_file_are_backed_by_user_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("MEMWING_HOME", str(tmp_path / "home"))

    with pytest.raises(SystemExit) as file_exit:
        main(["config", "file"])
    assert file_exit.value.code == 0
    config_path = Path(capsys.readouterr().out.strip())

    with pytest.raises(SystemExit) as set_exit:
        main(["config", "set", "api.port", "8123"])
    assert set_exit.value.code == 0
    assert load_json_config(config_path)["api"]["port"] == 8123
    capsys.readouterr()

    with pytest.raises(SystemExit) as get_exit:
        main(["config", "get", "api.port"])
    assert get_exit.value.code == 0
    assert capsys.readouterr().out.strip() == "8123"

    with pytest.raises(SystemExit) as unset_exit:
        main(["config", "unset", "api.port"])
    assert unset_exit.value.code == 0
    assert load_json_config(config_path)["api"] == {}


def test_memwing_start_print_env_uses_redacted_effective_runtime_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("MEMWING_HOME", str(tmp_path / "home"))

    with pytest.raises(SystemExit):
        main(["config", "set", "graph.neo4j.password", "secret-password"])
    capsys.readouterr()

    with pytest.raises(SystemExit) as exit_info:
        main(["start", "--profile", "lite", "--port", "8123", "--print-env"])

    assert exit_info.value.code == 0
    env = json.loads(capsys.readouterr().out)
    assert env["MEMWING_PROFILE"] == "lite"
    assert env["MEMWING_API_PORT"] == "8123"
    assert env["MEMWING_STORAGE_BACKEND"] == "sqlite"
    assert env["MEMWING_GRAPH_BACKEND"] == "disabled"
    assert env["MEMWING_EVIDENCE_BACKEND"] == "disabled"
    assert env["MEMWING_GRAPHITI_NEO4J_PASSWORD"] == "<redacted>"
    assert "DATABASE_URL" not in env


def test_memwing_start_passes_config_derived_env_into_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MEMWING_HOME", str(tmp_path / "home"))
    for name in (
        "DATABASE_URL",
        "MEMWING_PROFILE",
        "MEMWING_API_PORT",
        "MEMWING_STORAGE_BACKEND",
    ):
        monkeypatch.delenv(name, raising=False)
    captured: dict[str, object] = {}

    def fake_runtime_main(argv: list[str]) -> None:
        captured["argv"] = argv
        captured["env"] = dict(os.environ)

    monkeypatch.setattr("memwing.runtime_runner.main", fake_runtime_main)

    with pytest.raises(SystemExit):
        main(["config", "set", "profile", "production"])
    with pytest.raises(SystemExit):
        main(["config", "set", "database.url", "postgresql://memwing@localhost/memwing"])

    with pytest.raises(SystemExit) as exit_info:
        main(["start", "--port", "9123", "--api-only"])

    assert exit_info.value.code == 0
    assert captured["argv"] == ["--host", "127.0.0.1", "--port", "9123", "--api-only"]
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["MEMWING_PROFILE"] == "production"
    assert env["DATABASE_URL"] == "postgresql://memwing@localhost/memwing"
    assert env["MEMWING_API_PORT"] == "9123"


def test_memwing_doctor_lite_command_reports_profile_without_full_local_requirements(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("MEMWING_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OPENCLAW_CLI", "python")
    monkeypatch.setattr("memwing.doctor.run_command", _successful_openclaw_runner)

    with pytest.raises(SystemExit) as exit_info:
        main(["doctor", "--profile", "lite"])

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "profile: lite" in output
    assert "Lite does not require Neo4j" in output
    assert "database.url is required" not in output
    assert "openclaw_plugin" in output


def test_memwing_status_command_can_skip_api_health_probe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("MEMWING_HOME", str(tmp_path / "home"))

    with pytest.raises(SystemExit) as exit_info:
        main(["status", "--profile", "lite", "--no-health", "--json"])

    assert exit_info.value.code == 0
    status = json.loads(capsys.readouterr().out)
    assert status["profile"] == "lite"
    assert status["api_health"] == "not checked"
    assert status["storage_backend"] == "sqlite"


def test_memwing_openclaw_install_dry_run_uses_packaged_plugin_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("MEMWING_HOME", str(tmp_path / "home"))
    plugin_dir = tmp_path / "plugin"
    _plugin_artifact(tmp_path)

    with pytest.raises(SystemExit) as exit_info:
        main(
            [
                "openclaw",
                "install",
                "--dry-run",
                "--plugin-dir",
                str(plugin_dir),
                "--base-url",
                "http://memwing.test",
            ]
        )

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "openclaw plugins install --link" in output
    assert "openclaw config set --batch-json" in output
    assert "http://memwing.test" in output


def test_memwing_quickstart_lite_initializes_config_layout_and_sqlite_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    memwing_home = tmp_path / "home"
    monkeypatch.setenv("MEMWING_HOME", str(memwing_home))
    plugin_dir = _plugin_artifact(tmp_path)
    monkeypatch.setenv("MEMWING_OPENCLAW_PLUGIN_DIR", str(plugin_dir))
    installed: list[object] = []
    started: list[object] = []
    monkeypatch.setattr(
        "memwing.cli.install_openclaw_plugin",
        lambda plan, *, smoke: installed.append((plan, smoke)),
    )
    monkeypatch.setattr(
        "memwing.cli._start_runtime_background",
        lambda runtime_env, home, **_kwargs: started.append((runtime_env, home))
        or RuntimeLaunch(12345, home / "logs" / "runtime.log", home / "runtime.pid"),
    )

    with pytest.raises(SystemExit) as exit_info:
        main(["quickstart", "--profile", "lite"])

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "profile: lite" in output
    assert (memwing_home / "memwing.json").exists()
    assert (memwing_home / "memwing.db").exists()
    assert (memwing_home / "evidence").is_dir()
    assert (memwing_home / "graph").is_dir()
    assert installed
    assert started
    assert "openclaw: installed" in output
    assert "runtime: started pid=12345" in output


def test_memwing_quickstart_waits_for_runtime_health(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    memwing_home = tmp_path / "home"
    monkeypatch.setenv("MEMWING_HOME", str(memwing_home))
    monkeypatch.setenv("MEMWING_OPENCLAW_PLUGIN_DIR", str(_plugin_artifact(tmp_path)))
    monkeypatch.setattr("memwing.cli.install_openclaw_plugin", lambda _plan, *, smoke: None)
    calls: list[tuple[str, ...]] = []

    class FakeProcess:
        pid = 12345

        def poll(self) -> int | None:
            return None

        def terminate(self) -> None:
            raise AssertionError("healthy quickstart must not terminate runtime")

    def fake_popen(argv: list[str], **_kwargs: object) -> FakeProcess:
        calls.append(tuple(argv))
        return FakeProcess()

    monkeypatch.setattr("memwing.cli.subprocess.Popen", fake_popen)
    monkeypatch.setattr("memwing.cli.urlopen", lambda _url, timeout: SimpleNamespace(close=lambda: None))

    with pytest.raises(SystemExit) as exit_info:
        main(["quickstart", "--profile", "lite", "--startup-timeout-seconds", "0.1"])

    assert exit_info.value.code == 0
    assert calls
    assert "--allow-degraded-pipeline" not in calls[0]
    assert "runtime: healthy" in capsys.readouterr().out


def test_memwing_quickstart_fails_when_runtime_exits_before_health(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    memwing_home = tmp_path / "home"
    monkeypatch.setenv("MEMWING_HOME", str(memwing_home))
    monkeypatch.setenv("MEMWING_OPENCLAW_PLUGIN_DIR", str(_plugin_artifact(tmp_path)))
    monkeypatch.setattr("memwing.cli.install_openclaw_plugin", lambda _plan, *, smoke: None)

    class FakeProcess:
        pid = 12345

        def poll(self) -> int | None:
            return 1

        def terminate(self) -> None:
            return None

    monkeypatch.setattr("memwing.cli.subprocess.Popen", lambda *_args, **_kwargs: FakeProcess())

    with pytest.raises(SystemExit) as exit_info:
        main(["quickstart", "--profile", "lite", "--startup-timeout-seconds", "0.1"])

    assert exit_info.value.code == 2
    assert "exited before becoming healthy" in capsys.readouterr().err


def test_memwing_quickstart_lite_dry_run_does_not_write_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    memwing_home = tmp_path / "home"
    monkeypatch.setenv("MEMWING_HOME", str(memwing_home))

    with pytest.raises(SystemExit) as exit_info:
        main(["quickstart", "--profile", "lite", "--dry-run"])

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "profile: lite" in output
    assert "mode: dry-run" in output
    assert "would_write_config:" in output
    assert not (memwing_home / "memwing.json").exists()
    assert not (memwing_home / "memwing.db").exists()


def test_memwing_quickstart_full_local_writes_service_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    memwing_home = tmp_path / "home"
    monkeypatch.setenv("MEMWING_HOME", str(memwing_home))
    monkeypatch.setenv("MEMWING_OPENCLAW_PLUGIN_DIR", str(_plugin_artifact(tmp_path)))
    monkeypatch.setattr("memwing.cli.install_openclaw_plugin", lambda _plan, *, smoke: None)
    monkeypatch.setattr(
        "memwing.cli._start_runtime_background",
        lambda _env, home, **_kwargs: RuntimeLaunch(
            12345,
            home / "logs" / "runtime.log",
            home / "runtime.pid",
        ),
    )
    monkeypatch.setattr(
        "memwing.cli.verify_profile_services",
        lambda _config: ServiceReport(
            profile="full-local",
            checks=(
                ServiceCheck("postgres", "ok", "database.url is reachable at 127.0.0.1:5432"),
                ServiceCheck("qdrant", "ok", "evidence.qdrant.url is reachable at 127.0.0.1:6333"),
                ServiceCheck("neo4j", "ok", "graph.neo4j.uri is reachable at 127.0.0.1:7687"),
            ),
        ),
    )

    with pytest.raises(SystemExit) as exit_info:
        main(["quickstart", "--profile", "full-local"])

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "profile: full-local" in output
    assert "ok: postgres" in output
    assert "ok: qdrant" in output
    assert "ok: neo4j" in output
    config = load_json_config(memwing_home / "memwing.json")
    assert config["profile"] == "full-local"
    assert config["runtime"]["storageBackend"] == "postgres"
    assert config["runtime"]["modelRuntime"] == "openclaw"
    assert config["graph"]["backend"] == "graphiti"
    assert config["evidence"]["backend"] == "qdrant"


def test_memwing_quickstart_can_skip_openclaw_and_runtime_for_setup_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    memwing_home = tmp_path / "home"
    monkeypatch.setenv("MEMWING_HOME", str(memwing_home))

    with pytest.raises(SystemExit) as exit_info:
        main(["quickstart", "--profile", "lite", "--skip-openclaw", "--no-start"])

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "openclaw: skipped" in output
    assert "runtime: skipped" in output


def test_memwing_setup_production_renders_config_without_provisioning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    memwing_home = tmp_path / "home"
    monkeypatch.setenv("MEMWING_HOME", str(memwing_home))

    with pytest.raises(SystemExit) as exit_info:
        main(["setup", "--profile", "production"])

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "profile: production" in output
    assert "provisioning: skipped" in output
    config = load_json_config(memwing_home / "memwing.json")
    assert config["profile"] == "production"
    assert config["runtime"]["storageBackend"] == "postgres"
    assert config["runtime"]["modelRuntime"] == "openclaw"
    assert "url" not in config["database"]


def test_memwing_doctor_production_validates_external_endpoints_and_secrets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("MEMWING_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OPENCLAW_CLI", "python")
    monkeypatch.setenv("DATABASE_URL", "postgresql://memwing.example/memwing")
    monkeypatch.setenv("MEMWING_GRAPHITI_NEO4J_URI", "bolt://neo4j.example:7687")
    monkeypatch.setenv("MEMWING_GRAPHITI_NEO4J_USER", "neo4j")
    monkeypatch.setenv("MEMWING_QDRANT_URL", "https://qdrant.example")

    with pytest.raises(SystemExit) as exit_info:
        main(["setup", "--profile", "production"])
    assert exit_info.value.code == 0
    capsys.readouterr()

    with pytest.raises(SystemExit) as doctor_exit:
        main(["doctor", "--profile", "production"])

    assert doctor_exit.value.code == 1
    output = capsys.readouterr().out
    assert "graph.neo4j.password is required for production" in output
    assert "evidence.qdrant.apiKey is required for production" in output


def _plugin_artifact(tmp_path: Path) -> Path:
    plugin_dir = tmp_path / "plugin"
    (plugin_dir / "dist").mkdir(parents=True)
    (plugin_dir / "openclaw.plugin.json").write_text('{"id":"memwing"}', encoding="utf-8")
    (plugin_dir / "dist" / "openclaw.plugin.json").write_text(
        '{"id":"memwing"}',
        encoding="utf-8",
    )
    (plugin_dir / "dist" / "index.js").write_text("module.exports = {}", encoding="utf-8")
    return plugin_dir


def _successful_openclaw_runner(command: object) -> object:
    from memwing.openclaw_installer import OpenClawCommandResult

    argv = getattr(command, "argv")
    if argv[1:3] == ("plugins", "inspect"):
        stdout = json.dumps({"capabilities": [{"kind": "context-engine", "ids": ["memwing"]}]})
    elif argv[1:3] == ("config", "get") and argv[3] == "plugins.slots.contextEngine":
        stdout = json.dumps("memwing")
    elif argv[1:3] == ("config", "get") and argv[3] == "plugins.entries.memwing":
        stdout = json.dumps(
            {"enabled": True, "hooks": {"allowConversationAccess": True}}
        )
    else:
        stdout = ""
    return OpenClawCommandResult(tuple(argv), 0, stdout, "")
