from __future__ import annotations

import time
from typing import Any

import httpx

from memwing.api.platform import PlatformRef
from memwing.core.errors import ProviderTransientFailure
from memwing.core.types import JsonObject


class FeishuOpenApiError(ProviderTransientFailure):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(
            reason_code="feishu_openapi_error",
            safe_message=message,
        )

    def __str__(self) -> str:
        return self.message


class FeishuOpenApiPushSender:
    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        receive_id_type: str = "chat_id",
        api_base_url: str = "https://open.feishu.cn/open-apis",
        timeout_seconds: float = 10,
        client: httpx.Client | None = None,
    ) -> None:
        if receive_id_type not in {"open_id", "user_id", "union_id", "email", "chat_id"}:
            raise ValueError("receive_id_type is not supported by Feishu message send API")
        self._app_id = app_id
        self._app_secret = app_secret
        self._receive_id_type = receive_id_type
        self._api_base_url = api_base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._tenant_access_token: str | None = None
        self._tenant_access_token_expires_at = 0.0

    def send_interactive_message(
        self,
        platform_ref: PlatformRef,
        payload: JsonObject,
        trace_id: str,
    ) -> str:
        if payload.get("receive_id") != platform_ref.channel_id:
            raise FeishuOpenApiError("Feishu payload receive_id does not match platform ref channel")
        receive_id_type = platform_ref.receive_id_type or self._receive_id_type
        response = self._client.post(
            f"{self._api_base_url}/im/v1/messages",
            params={"receive_id_type": receive_id_type},
            headers={
                "Authorization": f"Bearer {self._get_tenant_access_token()}",
                "Content-Type": "application/json",
            },
            json={**payload, "uuid": trace_id},
        )
        result = _feishu_json(response, "send interactive message")
        data = result.get("data")
        if isinstance(data, dict):
            message_id = data.get("message_id")
            if isinstance(message_id, str) and message_id:
                return message_id
        log_id = response.headers.get("X-Tt-Logid")
        if log_id:
            return log_id
        raise FeishuOpenApiError("Feishu send response did not include message_id")

    def _get_tenant_access_token(self) -> str:
        now = time.monotonic()
        if self._tenant_access_token is not None and now < self._tenant_access_token_expires_at:
            return self._tenant_access_token

        response = self._client.post(
            f"{self._api_base_url}/auth/v3/tenant_access_token/internal",
            json={"app_id": self._app_id, "app_secret": self._app_secret},
        )
        result = _feishu_json(response, "get tenant_access_token")
        token = result.get("tenant_access_token")
        if not isinstance(token, str) or not token:
            raise FeishuOpenApiError("Feishu token response did not include tenant_access_token")
        expires_in = result.get("expire")
        if not isinstance(expires_in, int | float):
            expires_in = 7200
        self._tenant_access_token = token
        self._tenant_access_token_expires_at = now + max(0, float(expires_in) - 60)
        return token


def _feishu_json(response: httpx.Response, operation: str) -> dict[str, Any]:
    if response.status_code != 200:
        raise FeishuOpenApiError(
            _feishu_error_message(
                operation,
                f"HTTP {response.status_code}",
                response=response,
                response_text=response.text,
            )
        )
    try:
        result = response.json()
    except ValueError as exc:
        raise FeishuOpenApiError(
            _feishu_error_message(
                operation,
                "invalid JSON",
                response=response,
                response_text=response.text,
            )
        ) from exc
    if not isinstance(result, dict):
        raise FeishuOpenApiError(_feishu_error_message(operation, "non-object JSON", response=response))
    code = result.get("code")
    if code != 0:
        raise FeishuOpenApiError(
            _feishu_error_message(
                operation,
                f"code {code}",
                response=response,
                provider_message=result.get("msg"),
                provider_error=result.get("error"),
            )
        )
    return result


def _feishu_error_message(
    operation: str,
    summary: str,
    *,
    response: httpx.Response | None = None,
    provider_message: object | None = None,
    provider_error: object | None = None,
    response_text: str | None = None,
) -> str:
    parts = [f"Feishu {operation} failed: {summary}"]
    if isinstance(provider_message, str) and provider_message:
        parts.append(f"msg={provider_message}")
    if provider_error is not None:
        parts.append(f"error={_clip(str(provider_error))}")
    if response_text:
        parts.append(f"body={_clip(response_text)}")
    if response is not None:
        log_id = response.headers.get("X-Tt-Logid") or response.headers.get("x-tt-logid")
        if log_id:
            parts.append(f"log_id={log_id}")
    return "; ".join(parts)


def _clip(value: str, limit: int = 500) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3]}..."
