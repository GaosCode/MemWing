import asyncio
import os

import pytest

from memwing.infrastructure.llm.model_client import LLMModelRequest
from memwing.infrastructure.llm.openai_compatible import OpenAICompatibleChatClient
from memwing.infrastructure.llm.structured_output import parse_json_object


def test_openai_compatible_live_smoke_returns_json_object() -> None:
    if os.environ.get("MEMWING_LIVE_LLM") != "1":
        pytest.skip("set MEMWING_LIVE_LLM=1 to run live LLM smoke")

    client = OpenAICompatibleChatClient.from_env()

    async def scenario():
        return await client.complete(
            LLMModelRequest(
                system_prompt="Return only a JSON object.",
                user_prompt='Return exactly {"ok": true}.',
                trace_id="live_llm_smoke",
            )
        )

    response = asyncio.run(scenario())

    assert parse_json_object(response.text, source="live llm smoke") == {"ok": True}
