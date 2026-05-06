from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from memwing.config_store import default_config
from memwing.control_plane_launcher import ControlPlaneLauncherError, run_control_plane_command


def test_control_plane_launcher_starts_vite_with_config_derived_api_base(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text("{}", encoding="utf-8")
    captured: dict[str, object] = {}

    class FakeProcess:
        def wait(self) -> int:
            return 0

    def fake_popen(argv: list[str], **kwargs: object) -> FakeProcess:
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return FakeProcess()

    config = default_config()
    config["api"]["host"] = "0.0.0.0"
    config["api"]["port"] = 8123
    monkeypatch.setattr("memwing.control_plane_launcher._ui_responds", lambda _url: False)
    monkeypatch.setattr("memwing.control_plane_launcher._find_static_assets_dir", lambda: None)
    monkeypatch.setattr("memwing.control_plane_launcher._find_frontend_source_dir", lambda: frontend)
    monkeypatch.setattr("memwing.control_plane_launcher.shutil.which", lambda name: f"/bin/{name}")
    monkeypatch.setattr("memwing.control_plane_launcher.subprocess.Popen", fake_popen)

    exit_code = run_control_plane_command(
        SimpleNamespace(
            host="127.0.0.1",
            port=5174,
            api_base_url=None,
            open=False,
            mock=False,
        ),
        config,
    )

    assert exit_code == 0
    assert captured["argv"] == [
        "/bin/npm",
        "run",
        "dev",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        "5174",
    ]
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    env = kwargs["env"]
    assert isinstance(env, dict)
    assert env["VITE_MEMWING_API_PROXY_TARGET"] == "http://127.0.0.1:8123"
    assert "Control Plane: starting local frontend server" in capsys.readouterr().out


def test_control_plane_launcher_fails_when_frontend_assets_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("memwing.control_plane_launcher._ui_responds", lambda _url: False)
    monkeypatch.setattr("memwing.control_plane_launcher._find_static_assets_dir", lambda: None)
    monkeypatch.setattr("memwing.control_plane_launcher._find_frontend_source_dir", lambda: None)

    with pytest.raises(ControlPlaneLauncherError, match="frontend assets are unavailable"):
        run_control_plane_command(
            SimpleNamespace(
                host="127.0.0.1",
                port=5173,
                api_base_url=None,
                open=False,
                mock=False,
            ),
            default_config(),
        )
