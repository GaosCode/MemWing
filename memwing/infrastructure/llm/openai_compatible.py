from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from memwing.infrastructure.llm.errors import LLMOutputSchemaError, LLMProviderError
from memwing.infrastructure.llm.model_client import LLMModelClient, LLMModelRequest, LLMModelResponse


@dataclass(frozen=True, slots=True)
class OpenAICompatibleConfig:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float = 60.0
    temperature: float = 0.0
    response_format_json: bool = False


class OpenAICompatibleTransport(Protocol):
    def post_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout_seconds: float,
    ) -> Mapping[str, object]:
        ...


class OpenAICompatibleChatClient(LLMModelClient):
    def __init__(
        self,
        config: OpenAICompatibleConfig,
        *,
        transport: OpenAICompatibleTransport | None = None,
    ) -> None:
        if not config.api_key.strip():
            raise ValueError("OpenAI-compatible api_key is required")
        if not config.base_url.strip():
            raise ValueError("OpenAI-compatible base_url is required")
        if not config.model.strip():
            raise ValueError("OpenAI-compatible model is required")
        self._config = config
        self._transport = transport or UrllibOpenAICompatibleTransport()

    @classmethod
    def from_env(
        cls,
        *,
        prefix: str = "MEMWING_LLM",
        transport: OpenAICompatibleTransport | None = None,
    ) -> OpenAICompatibleChatClient:
        api_key = _required_env(f"{prefix}_API_KEY")
        model = _required_env(f"{prefix}_MODEL")
        base_url = os.environ.get(f"{prefix}_BASE_URL", "https://api.openai.com/v1")
        timeout_seconds = float(os.environ.get(f"{prefix}_TIMEOUT_SECONDS", "60"))
        return cls(
            OpenAICompatibleConfig(
                api_key=api_key,
                base_url=base_url,
                model=model,
                timeout_seconds=timeout_seconds,
                response_format_json=_env_bool(f"{prefix}_RESPONSE_FORMAT_JSON"),
            ),
            transport=transport,
        )

    async def complete(self, request: LLMModelRequest) -> LLMModelResponse:
        payload = self._payload(request, include_response_format=self._config.response_format_json)
        try:
            data = self._transport.post_json(
                url=f"{self._config.base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._config.api_key}",
                    "Content-Type": "application/json",
                },
                payload=payload,
                timeout_seconds=self._config.timeout_seconds,
            )
        except _OpenAICompatibleHTTPError as exc:
            if self._config.response_format_json and exc.status_code in {400, 422}:
                data = self._transport.post_json(
                    url=f"{self._config.base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._config.api_key}",
                        "Content-Type": "application/json",
                    },
                    payload=self._payload(request, include_response_format=False),
                    timeout_seconds=self._config.timeout_seconds,
                )
            else:
                raise LLMProviderError(
                    f"OpenAI-compatible provider returned HTTP {exc.status_code}"
                ) from exc

        return LLMModelResponse(
            text=_message_content(data),
            provider="openai-compatible",
            model=self._config.model,
        )

    def _payload(
        self,
        request: LLMModelRequest,
        *,
        include_response_format: bool,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self._config.model,
            "messages": (
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ),
            "temperature": self._config.temperature,
        }
        if include_response_format:
            payload["response_format"] = {"type": "json_object"}
        return payload


class UrllibOpenAICompatibleTransport:
    def post_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout_seconds: float,
    ) -> Mapping[str, object]:
        body = json.dumps(payload).encode("utf-8")
        request = Request(url, data=body, headers=dict(headers), method="POST")
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                data = response.read().decode("utf-8")
        except HTTPError as exc:
            raise _OpenAICompatibleHTTPError(exc.code) from exc
        except URLError as exc:
            raise LLMProviderError("OpenAI-compatible provider request failed") from exc

        try:
            parsed = json.loads(data)
        except json.JSONDecodeError as exc:
            raise LLMOutputSchemaError("OpenAI-compatible provider returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise LLMOutputSchemaError("OpenAI-compatible provider response must be a JSON object")
        return parsed


class _OpenAICompatibleHTTPError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


def _message_content(data: Mapping[str, object]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMOutputSchemaError("OpenAI-compatible response requires choices")
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise LLMOutputSchemaError("OpenAI-compatible response choice must be an object")
    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise LLMOutputSchemaError("OpenAI-compatible response choice requires message")
    content = message.get("content")
    if not isinstance(content, str) or not content:
        raise LLMOutputSchemaError("OpenAI-compatible response message requires content")
    return content


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise ValueError(f"{name} is required")
    return value


def _env_bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}
