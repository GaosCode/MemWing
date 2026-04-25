from __future__ import annotations

from typing import Any

import httpx

from memwing_benchmark.json_utils import parse_json_object


class VolcengineArkChatModel:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def complete_json(self, *, system: str, user: str, temperature: float = 0.0) -> dict[str, Any]:
        try:
            return self._complete_with_openai_sdk(system=system, user=user, temperature=temperature)
        except Exception:
            return self._complete_with_httpx(
                system=system,
                user=user,
                temperature=temperature,
                include_response_format=True,
            )

    def _complete_with_openai_sdk(
        self, *, system: str, user: str, temperature: float
    ) -> dict[str, Any]:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout_seconds)
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or ""
        return parse_json_object(content)

    def _complete_with_httpx(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        include_response_format: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        if include_response_format:
            payload["response_format"] = {"type": "json_object"}
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if include_response_format and exc.response.status_code in {400, 422}:
                return self._complete_with_httpx(
                    system=system,
                    user=user,
                    temperature=temperature,
                    include_response_format=False,
                )
            raise

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return parse_json_object(content)
