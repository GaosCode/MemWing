from __future__ import annotations

import json

import pytest

from memwing.openclaw_smoke import OpenClawSmokeError, verify_runtime_inspect


def test_verify_runtime_inspect_accepts_context_engine_capability() -> None:
    verify_runtime_inspect(
        json.dumps({"capabilities": [{"kind": "context-engine", "ids": ["memwing"]}]})
    )


def test_verify_runtime_inspect_accepts_plugin_context_engine_ids() -> None:
    verify_runtime_inspect(
        json.dumps({"capabilities": [], "plugin": {"contextEngineIds": ["memwing"]}})
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
