from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from typing import Any, AsyncContextManager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from memwing.api.openclaw_http import handle_openclaw_http_request
from memwing.bootstrap import postgres_runtime_context
from memwing.ports.agent_runtime import AgentRuntimePort


RuntimeContextFactory = Callable[[], AsyncContextManager[AgentRuntimePort]]


def create_app(
    *,
    runtime_context_factory: RuntimeContextFactory = postgres_runtime_context,
) -> FastAPI:
    state: dict[str, AgentRuntimePort] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with runtime_context_factory() as runtime:
            state["runtime"] = runtime
            yield
            state.clear()

    app = FastAPI(title="MemWing API", version="0.1.0", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> Mapping[str, bool]:
        return {"ok": True}

    @app.post("/{path:path}")
    async def post_route(path: str, request: Request) -> JSONResponse:
        payload = await _json_payload(request)
        response = await handle_openclaw_http_request(
            method="POST",
            path=f"/{path}",
            payload=payload,
            runtime=state["runtime"],
        )
        return JSONResponse(status_code=response.status_code, content=response.body)

    return app


async def _json_payload(request: Request) -> Mapping[str, object]:
    if request.headers.get("content-length") == "0":
        return {}
    value: Any = await request.json()
    if isinstance(value, dict):
        return value
    return {"payload": value}


app = create_app()
