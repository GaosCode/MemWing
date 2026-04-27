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


def test_list_messages_uses_bot_identity_by_default(monkeypatch) -> None:
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return Completed(0, '{"data":{"items":[]}}')

    monkeypatch.setattr(subprocess, "run", fake_run)
    cli = FeishuCli("lark-cli")

    cli.list_messages(chat_id="oc_1")

    args, kwargs = calls[0]
    assert args[:5] == ["lark-cli", "im", "+chat-messages-list", "--as", "bot"]
    assert "--format" in args
    assert kwargs["cwd"] is None


def test_create_chat_invites_unique_bot_app_ids(monkeypatch) -> None:
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return Completed(0, '{"data":{"chat_id":"oc_1"}}')

    monkeypatch.setattr(subprocess, "run", fake_run)
    cli = FeishuCli("lark-cli")

    cli.create_chat(name="bench", bot_app_ids=["cli_a", "cli_b", "cli_a", ""])

    args, _ = calls[0]
    assert args[:3] == ["lark-cli", "im", "+chat-create"]
    assert args[args.index("--bots") + 1] == "cli_a,cli_b"


def test_current_app_id_uses_cached_auth_status_from_preflight(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _: "/opt/homebrew/bin/lark-cli")
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return Completed(0, '{"appId":"cli_reader","tokenStatus":"valid","scope":""}')

    monkeypatch.setattr(subprocess, "run", fake_run)
    cli = FeishuCli("lark-cli")

    cli.ensure_ready()

    assert cli.current_app_id() == "cli_reader"
    assert calls == [["lark-cli", "auth", "status"]]


def test_wait_for_bot_reply_matches_app_id_sender(monkeypatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)

    def fake_run(args, **kwargs):
        return Completed(
            0,
            (
                '{"data":{"messages":[{"sender":{"id":"cli_bot",'
                '"id_type":"app_id","sender_type":"app"}}]}}'
            ),
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    cli = FeishuCli("lark-cli")

    reply = cli.wait_for_bot_reply(
        chat_id="oc_1",
        since="2026-04-26T01:00:00+00:00",
        bot_ids=["ou_wrong", "cli_bot"],
        timeout_seconds=1,
    )

    assert reply["sender"]["id"] == "cli_bot"


def test_wait_for_bot_reply_times_out_when_lark_cli_hangs(monkeypatch) -> None:
    monotonic_values = iter([0.0, 0.0, 0.6, 1.2, 1.2])
    sleeps = []

    monkeypatch.setattr("time.monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr("time.sleep", lambda seconds: sleeps.append(seconds))

    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs.get("timeout") or 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    cli = FeishuCli("lark-cli")

    try:
        cli.wait_for_bot_reply(
            chat_id="oc_1",
            since="2026-04-26T01:00:00+00:00",
            bot_ids=["cli_bot"],
            timeout_seconds=1,
            poll_seconds=0.5,
        )
    except BenchmarkError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected BenchmarkError")

    assert "Timed out waiting for bot reply after 1s" in message
    assert "Feishu CLI command timed out" in message
    assert cli.commands[0].exit_code == 124


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
