from __future__ import annotations

import json

import pytest

from memwing.openclaw_smoke import OpenClawSmokeError, verify_runtime_inspect
from memwing.openclaw_smoke import render_status_text, verify_context_engine


def test_verify_runtime_inspect_accepts_context_engine_capability() -> None:
    verify_runtime_inspect(
        json.dumps({"capabilities": [{"kind": "context-engine", "ids": ["memwing"]}]})
    )


def test_verify_runtime_inspect_accepts_plugin_context_engine_ids() -> None:
    verify_runtime_inspect(
        json.dumps({"capabilities": [], "plugin": {"contextEngineIds": ["memwing"]}})
    )


def test_verify_context_engine_accepts_memory_slot_label() -> None:
    verify_context_engine(json.dumps("memwing"), label="plugins.slots.memory")


def test_render_status_text_requires_memwing_memory_slot() -> None:
    with pytest.raises(OpenClawSmokeError, match="plugins.slots.memory"):
        render_status_text(
            inspect_stdout=json.dumps(
                {"capabilities": [{"kind": "context-engine", "ids": ["memwing"]}]}
            ),
            context_slot_stdout=json.dumps("memwing"),
            memory_slot_stdout=json.dumps("memory-core"),
            entry_stdout=json.dumps(
                {
                    "enabled": True,
                    "hooks": {"allowConversationAccess": True},
                    "config": {"nativeMemoryTools": True},
                }
            ),
            inspect_argv=("openclaw", "plugins", "inspect", "memwing"),
        )


def test_verify_runtime_inspect_surfaces_plugin_diagnostics() -> None:
    with pytest.raises(OpenClawSmokeError, match="contracts.tools"):
        verify_runtime_inspect(
            json.dumps(
                {
                    "capabilities": [],
                    "diagnostics": [
                        {
                            "level": "error",
                            "message": "plugin must declare contracts.tools before registering agent tools",
                        }
                    ],
                }
            )
        )
