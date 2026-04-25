from pathlib import Path

from typer.testing import CliRunner

from memwing_benchmark.cli import app, make_idempotency_key


def test_cli_non_live_creates_run_outputs(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--config",
            "config.example.json",
            "--backend",
            "openclaw-native",
            "--cases",
            "cases.json",
            "--case-id",
            "bs001",
            "--runs-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    run_dirs = list(tmp_path.iterdir())
    assert len(run_dirs) == 1
    assert (run_dirs[0] / "normalized.jsonl").exists()
    assert (run_dirs[0] / "scores.json").exists()
    assert (run_dirs[0] / "report.md").exists()


def test_idempotency_key_is_short_stable_and_traceable() -> None:
    key = make_idempotency_key(
        run_id="20260425-133837",
        backend="openclaw-native",
        case_id="bs001",
        item_id="bs001_s1",
    )

    assert key == make_idempotency_key(
        run_id="20260425-133837",
        backend="openclaw-native",
        case_id="bs001",
        item_id="bs001_s1",
    )
    assert len(key) <= 50
    assert key.startswith("mwb-bs001-bs001-s1-")
    assert "_" not in key
