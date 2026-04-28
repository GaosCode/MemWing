from pathlib import Path

from memwing_benchmark.config import load_config, sanitize_config_for_run


def test_load_config_and_redact_api_key() -> None:
    config = load_config(Path("config.example.json"))
    sanitized = sanitize_config_for_run(config)

    assert config.judge.model == "YOUR_MODEL_ID"
    assert "api_key" not in sanitized["judge"]
    assert sanitized["judge"]["provider"] == "volcengine_ark"
    assert sanitized["paths"]["openclaw_repo_dir"] == "/absolute/path/to/openclaw"
