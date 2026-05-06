from __future__ import annotations

from pathlib import Path

from memwing.config_store import default_config
from memwing.runtime_env import build_runtime_env


def test_lite_runtime_env_uses_sqlite_and_disables_service_backends(tmp_path: Path) -> None:
    env = {"MEMWING_HOME": str(tmp_path / "home"), "DATABASE_URL": "postgresql://ignored"}

    runtime_env = build_runtime_env(default_config(), base_env=env)

    assert runtime_env.env["MEMWING_PROFILE"] == "lite"
    assert runtime_env.env["MEMWING_STORAGE_BACKEND"] == "sqlite"
    assert runtime_env.env["MEMWING_LITE_DB_PATH"] == str(tmp_path / "home" / "memwing.db")
    assert runtime_env.env["MEMWING_GRAPH_BACKEND"] == "disabled"
    assert runtime_env.env["MEMWING_EVIDENCE_BACKEND"] == "disabled"
    assert "DATABASE_URL" not in runtime_env.env
