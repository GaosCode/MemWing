import subprocess

from memwing_benchmark.channels.feishu_cli import FeishuCli
from memwing_benchmark.errors import BenchmarkError


class Completed:
    def __init__(self, returncode: int, stdout: str = "{}", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_feishu_cli_uses_installed_lark_cli_binary(monkeypatch) -> None:
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return Completed(0, '{"data":{"message_id":"om_1","chat_id":"oc_1"}}')

    monkeypatch.setattr(subprocess, "run", fake_run)
    cli = FeishuCli("lark-cli")

    cli.send_text(chat_id="oc_1", text="hello", idempotency_key="k1")

    args, kwargs = calls[0]
    assert args[:3] == ["lark-cli", "im", "+messages-send"]
    assert "go" not in args
    assert "--format" not in args
    assert kwargs["cwd"] is None


def test_preflight_reports_install_hint_when_binary_missing(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _: None)
    cli = FeishuCli("lark-cli")

    try:
        cli.ensure_ready()
    except BenchmarkError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected BenchmarkError")

    assert "npm install -g @larksuite/cli" in message


def test_preflight_reports_login_hint_when_not_configured(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _: "/opt/homebrew/bin/lark-cli")
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return Completed(
            2,
            '{"ok":false,"error":{"type":"config","message":"not configured"}}',
            "",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    cli = FeishuCli("lark-cli")

    try:
        cli.ensure_ready()
    except BenchmarkError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected BenchmarkError")

    assert "lark-cli config init --new" in message
    assert "lark-cli auth login --recommend" in message
    assert calls == [["lark-cli", "auth", "status"]]


def test_preflight_reports_missing_required_scope(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _: "/opt/homebrew/bin/lark-cli")

    def fake_run(args, **kwargs):
        return Completed(
            0,
            '{"tokenStatus":"valid","scope":"im:message.group_msg:get_as_user"}',
            "",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    cli = FeishuCli("lark-cli")

    try:
        cli.ensure_ready(required_scopes=["im:message.send_as_user"])
    except BenchmarkError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected BenchmarkError")

    assert "im:message.send_as_user" in message
    assert 'lark-cli auth login --scope "im:message.send_as_user"' in message
