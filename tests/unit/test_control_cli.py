from __future__ import annotations

import json
import inspect
from typing import Any

import pytest

import memwing.control_cli as control_cli
from memwing.cli import main


class FakeControlClient:
    requests: list[tuple[str, str, dict[str, str], dict[str, object] | None]] = []
    response: dict[str, object] = {
        "items": (
            {
                "memory_id": "mem_001",
                "title": "Remember API decision",
                "status": "pending",
            },
        ),
        "next_cursor": None,
    }

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        self.requests.append((method, path, params or {}, json_body))
        return self.response


@pytest.fixture(autouse=True)
def fake_control_client(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeControlClient.requests = []
    FakeControlClient.response = {
        "items": (
            {
                "memory_id": "mem_001",
                "title": "Remember API decision",
                "status": "pending",
            },
        ),
        "next_cursor": None,
    }
    monkeypatch.setattr("memwing.control_cli.ControlClient", FakeControlClient)


def test_control_memories_list_defaults_to_table_output_and_calls_http(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("MEMWING_HOME", str(tmp_path / "home"))

    with pytest.raises(SystemExit) as exit_info:
        main(["control", "memories", "list", "--project", "project_001"])

    assert exit_info.value.code == 0
    assert FakeControlClient.requests == [
        (
            "GET",
            "/v1/control/memories",
            {"project_memory_space_id": "project_001"},
            None,
        )
    ]
    output = capsys.readouterr().out
    assert "memory_id" in output
    assert "mem_001" in output
    assert "Remember API decision" in output


def test_control_read_commands_support_json_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("MEMWING_HOME", str(tmp_path / "home"))
    FakeControlClient.response = {"memory_id": "mem_001", "status": "approved"}

    with pytest.raises(SystemExit) as exit_info:
        main(["control", "memories", "show", "mem_001", "--project", "project_001", "--json"])

    assert exit_info.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"memory_id": "mem_001", "status": "approved"}
    assert FakeControlClient.requests[0][:3] == (
        "GET",
        "/v1/control/memories/mem_001",
        {"project_memory_space_id": "project_001"},
    )


def test_control_mutation_requires_confirmation_before_http_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("MEMWING_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("builtins.input", lambda _prompt: "no")

    with pytest.raises(SystemExit) as exit_info:
        main(["control", "memories", "archive", "mem_001", "--project", "project_001"])

    assert exit_info.value.code == 1
    assert FakeControlClient.requests == []
    assert "aborted" in capsys.readouterr().out


def test_control_mutation_yes_sends_mutation_envelope_over_http(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    monkeypatch.setenv("MEMWING_HOME", str(tmp_path / "home"))
    FakeControlClient.response = {"ok": True, "item": {"memory_id": "mem_001"}}

    with pytest.raises(SystemExit) as exit_info:
        main(
            [
                "control",
                "memories",
                "approve",
                "mem_001",
                "--project",
                "project_001",
                "--actor-id",
                "operator_001",
                "--reason",
                "reviewed",
                "--yes",
            ]
        )

    assert exit_info.value.code == 0
    method, path, params, body = FakeControlClient.requests[0]
    assert (method, path, params) == (
        "POST",
        "/v1/memory/mem_001/approve",
        {"project_memory_space_id": "project_001"},
    )
    assert body is not None
    assert body["actor_id"] == "operator_001"
    assert body["reason"] == "reviewed"
    assert isinstance(body["idempotency_key"], str)


def test_control_push_send_uses_platform_route(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    monkeypatch.setenv("MEMWING_HOME", str(tmp_path / "home"))

    with pytest.raises(SystemExit):
        main(
            [
                "control",
                "push",
                "send",
                "candidate_001",
                "--platform",
                "feishu",
                "--project",
                "project_001",
                "--yes",
            ]
        )

    assert FakeControlClient.requests[0][0:3] == (
        "POST",
        "/v1/platforms/feishu/push-candidates/candidate_001/send",
        {"project_memory_space_id": "project_001"},
    )


def test_control_sources_purge_sends_required_purge_level(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    monkeypatch.setenv("MEMWING_HOME", str(tmp_path / "home"))

    with pytest.raises(SystemExit) as exit_info:
        main(
            [
                "control",
                "sources",
                "purge",
                "source_001",
                "--project",
                "project_001",
                "--yes",
            ]
        )

    assert exit_info.value.code == 0
    method, path, _params, body = FakeControlClient.requests[0]
    assert (method, path) == ("POST", "/v1/source-events/source_001/purge")
    assert body is not None
    assert body["purge_level"] == "memwing_redaction"


def test_control_cli_stays_on_http_boundary() -> None:
    assert "memwing.application" not in inspect.getsource(control_cli)
