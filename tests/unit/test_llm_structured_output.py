import pytest

from memwing.infrastructure.llm.errors import LLMOutputSchemaError
from memwing.infrastructure.llm.structured_output import parse_json_object


def test_parse_json_object_accepts_plain_json() -> None:
    parsed = parse_json_object('{"title":"Project scope","items":[1]}', source="unit")

    assert parsed == {"title": "Project scope", "items": [1]}


def test_parse_json_object_accepts_fenced_json() -> None:
    parsed = parse_json_object('```json\n{"title":"Project scope"}\n```', source="unit")

    assert parsed == {"title": "Project scope"}


def test_parse_json_object_rejects_arrays() -> None:
    with pytest.raises(LLMOutputSchemaError, match="unit must be a JSON object"):
        parse_json_object('[{"title":"Project scope"}]', source="unit")


def test_parse_json_object_rejects_bad_json_without_raw_payload_leak() -> None:
    with pytest.raises(LLMOutputSchemaError) as exc_info:
        parse_json_object("not-json secret-token-123", source="unit")

    assert "secret-token-123" not in str(exc_info.value)
