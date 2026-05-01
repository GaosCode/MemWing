from __future__ import annotations

import json
from pathlib import Path


PLUGIN_MANIFEST = Path("memwing/integrations/openclaw/openclaw.plugin.json")


def test_openclaw_plugin_schema_accepts_model_runtime_config() -> None:
    manifest = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
    schema = manifest["configSchema"]

    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {
        "memwingBaseUrl",
        "modelRuntime",
        "models",
        "modelTimeoutSeconds",
    }
    assert schema["properties"]["modelRuntime"]["enum"] == ["openclaw"]
    assert schema["properties"]["modelTimeoutSeconds"]["exclusiveMinimum"] == 0

    models = schema["properties"]["models"]
    assert models["type"] == "object"
    assert models["additionalProperties"] is False
    assert set(models["properties"]) == {
        "pageMemory",
        "longTermFilter",
        "graphitiExtraction",
        "graphitiEmbedding",
        "graphitiRerank",
    }
    assert models["properties"]["graphitiExtraction"]["type"] == ["string", "null"]


def test_openclaw_plugin_schema_allows_minimal_runtime_config() -> None:
    manifest = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
    schema = manifest["configSchema"]

    payload = {
        "memwingBaseUrl": "http://127.0.0.1:8000",
        "modelRuntime": "openclaw",
    }

    assert set(payload).issubset(schema["properties"])
    assert payload["modelRuntime"] in schema["properties"]["modelRuntime"]["enum"]


def test_openclaw_plugin_schema_allows_role_specific_model_refs() -> None:
    manifest = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
    models_schema = manifest["configSchema"]["properties"]["models"]

    payload = {
        "pageMemory": "current",
        "longTermFilter": "current",
        "graphitiExtraction": "current",
        "graphitiEmbedding": "current",
        "graphitiRerank": "current",
    }

    assert set(payload).issubset(models_schema["properties"])
    for model_ref in payload.values():
        assert isinstance(model_ref, str)
        assert model_ref


def test_openclaw_plugin_schema_allows_null_role_model_refs() -> None:
    manifest = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
    models_schema = manifest["configSchema"]["properties"]["models"]

    assert "null" in models_schema["properties"]["pageMemory"]["type"]
