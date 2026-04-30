import asyncio
import os

import pytest

from memwing.infrastructure.llm.model_client import LLMModelRequest
from memwing.infrastructure.llm.openclaw_runtime import OpenClawRuntimeLLMClient
from memwing.infrastructure.llm.structured_output import parse_json_object


@pytest.mark.skipif(
    os.environ.get("MEMWING_LIVE_OPENCLAW_LLM") != "1",
    reason="set MEMWING_LIVE_OPENCLAW_LLM=1 to run OpenClaw runtime LLM smoke test",
)
def test_openclaw_runtime_llm_live_returns_json_object() -> None:
    client = OpenClawRuntimeLLMClient.from_env()

    async def scenario():
        return await client.complete(
            LLMModelRequest(
                system_prompt="Return exactly one compact JSON object and no prose.",
                user_prompt='Return {"ok": true}.',
                trace_id="openclaw_runtime_live",
            )
        )

    response = asyncio.run(scenario())
    parsed = parse_json_object(response.text, source="OpenClaw runtime live smoke test")

    assert parsed["ok"] is True
