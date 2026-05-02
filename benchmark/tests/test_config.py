from pathlib import Path

from memwing_benchmark.config import load_config, sanitize_config_for_run, validate_config_for_backend
from memwing_benchmark.errors import BenchmarkError
from memwing_benchmark.json_utils import dumps_json


def test_load_config_and_redact_api_key() -> None:
    config = load_config(Path("config.example.json"))
    sanitized = sanitize_config_for_run(config)

    assert config.judge.model == "YOUR_MODEL_ID"
    assert "api_key" not in sanitized["judge"]
    assert sanitized["judge"]["provider"] == "volcengine_ark"
    assert sanitized["paths"]["openclaw_repo_dir"] == "/absolute/path/to/openclaw"
    assert config.memwing.base_url == "http://127.0.0.1:8000"
    assert config.memwing.normalized_base_url == "http://127.0.0.1:8000"
    assert sanitized["memwing"]["base_url"] == "http://127.0.0.1:8000"


def test_validate_memwing_backend_requires_runtime_scope_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "config.local.json"
    config_path.write_text(
        dumps_json(
            {
                "memwing": {
                    "base_url": "",
                    "project_memory_space_id": "project_001",
                    "group_id": "benchmark_group",
                    "thread_id": "benchmark_thread",
                }
            }
        ),
        encoding="utf-8",
    )
    config = load_config(config_path)

    try:
        validate_config_for_backend(config, backend="memwing")
    except BenchmarkError as exc:
        assert "memwing.base_url is required" in str(exc)
    else:
        raise AssertionError("expected BenchmarkError")


def test_validate_memwing_backend_rejects_whitespace_base_url(tmp_path: Path) -> None:
    config_path = tmp_path / "config.local.json"
    config_path.write_text(
        dumps_json(
            {
                "memwing": {
                    "base_url": "   ",
                    "project_memory_space_id": "project_001",
                    "group_id": "benchmark_group",
                    "thread_id": "benchmark_thread",
                }
            }
        ),
        encoding="utf-8",
    )
    config = load_config(config_path)

    try:
        validate_config_for_backend(config, backend="memwing")
    except BenchmarkError as exc:
        assert "memwing.base_url is required" in str(exc)
    else:
        raise AssertionError("expected BenchmarkError")


def test_sanitize_config_for_run_removes_config_local_private_values(tmp_path: Path) -> None:
    config_path = tmp_path / "config.local.json"
    config_path.write_text(
        dumps_json(
            {
                "judge": {"api_key": "sk_private"},
                "feishu": {
                    "bot_app_id": "cli_a_private",
                    "bot_open_id": "ou_private",
                    "mention_text": "<at user_id=\"ou_private\">Bot</at>",
                    "chat_id": "oc_private",
                    "seed_chat_id": "oc_seed_private",
                    "probe_chat_id": "oc_probe_private",
                },
                "memwing": {
                    "base_url": "https://user:password@memwing.example.test:8443",
                    "group_id": "private_group",
                    "thread_id": "private_thread",
                    "shared_group_id": "private_shared",
                },
            }
        ),
        encoding="utf-8",
    )
    sanitized = sanitize_config_for_run(load_config(config_path))

    assert "api_key" not in sanitized["judge"]
    assert sanitized["feishu"]["bot_app_id"] == ""
    assert sanitized["feishu"]["bot_open_id"] == ""
    assert sanitized["feishu"]["mention_text"] == ""
    assert sanitized["feishu"]["chat_id"] == ""
    assert sanitized["feishu"]["seed_chat_id"] == ""
    assert sanitized["feishu"]["probe_chat_id"] == ""
    assert sanitized["memwing"]["base_url"] == "https://memwing.example.test:8443"
    assert sanitized["memwing"]["group_id"] == ""
    assert sanitized["memwing"]["thread_id"] == ""
    assert sanitized["memwing"]["shared_group_id"] == ""
