from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx


class ControlClientError(RuntimeError):
    pass


class ControlClient:
    def __init__(self, base_url: str, *, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json_body: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        try:
            with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
                response = client.request(
                    method,
                    path,
                    params=dict(params or {}),
                    json=dict(json_body) if json_body is not None else None,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip() or exc.response.reason_phrase
            raise ControlClientError(
                f"Control Plane request failed: {exc.response.status_code} {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ControlClientError(f"Control Plane request failed: {exc}") from exc
        if not response.content:
            return {}
        payload = response.json()
        if not isinstance(payload, dict):
            raise ControlClientError("Control Plane response must be a JSON object")
        return payload
