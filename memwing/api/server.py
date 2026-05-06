from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from typing import Any, AsyncContextManager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from memwing.api.benchmark_admin import handle_benchmark_admin_request
from memwing.api.control_http import ControlHttpServices, handle_control_http_request
from memwing.api.env import load_app_env
from memwing.api.openclaw_http import handle_openclaw_http_request
from memwing.api.pipeline import (
    handle_pipeline_await_request,
    handle_pipeline_readiness_request,
)
from memwing.api.runtime_config import benchmark_admin_enabled_from_env
from memwing.application.benchmark_admin_service import BenchmarkAdminService
from memwing.application.control_service import ControlService
from memwing.application.pipeline_readiness_service import PipelineReadinessService
from memwing.application.scope_resolver import ScopeResolver
from memwing.application.source_redaction_service import SourceRedactionService
from memwing.bootstrap import MemWingApiRuntimeContext, runtime_context_from_env
from memwing.ports.agent_runtime import AgentRuntimePort


RuntimeContextFactory = Callable[[], AsyncContextManager[AgentRuntimePort | MemWingApiRuntimeContext]]


load_app_env()


def create_app(
    *,
    runtime_context_factory: RuntimeContextFactory = runtime_context_from_env,
) -> FastAPI:
    state: dict[
        str,
        AgentRuntimePort
        | BenchmarkAdminService
        | PipelineReadinessService
        | ControlService
        | ScopeResolver
        | SourceRedactionService
        | None,
    ] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with runtime_context_factory() as context:
            runtime_context = _api_runtime_context(context)
            state["runtime"] = runtime_context.runtime
            state["benchmark_admin"] = runtime_context.benchmark_admin
            state["pipeline_readiness"] = runtime_context.pipeline_readiness
            state["control"] = runtime_context.control
            state["control_scope_resolver"] = runtime_context.control_scope_resolver
            state["source_redaction"] = runtime_context.source_redaction
            yield
            state.clear()

    app = FastAPI(title="MemWing API", version="0.1.0", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> Mapping[str, bool]:
        return {"ok": True}

    if benchmark_admin_enabled_from_env():

        @app.post("/v1/memwing/admin/benchmark/{admin_path:path}")
        async def benchmark_admin_route(admin_path: str, request: Request) -> JSONResponse:
            payload = await _json_payload(request)
            response = await handle_benchmark_admin_request(
                path=f"/v1/memwing/admin/benchmark/{admin_path}",
                payload=payload,
                service=_benchmark_admin_service(state.get("benchmark_admin")),
            )
            return JSONResponse(status_code=response.status_code, content=response.body)

    @app.post("/v1/memwing/pipeline/readiness")
    async def pipeline_readiness_route(request: Request) -> JSONResponse:
        payload = await _json_payload(request)
        response = await handle_pipeline_readiness_request(
            payload=payload,
            service=_pipeline_readiness_service(state.get("pipeline_readiness")),
        )
        return JSONResponse(status_code=response.status_code, content=response.body)

    @app.post("/v1/memwing/pipeline/await")
    async def pipeline_await_route(request: Request) -> JSONResponse:
        payload = await _json_payload(request)
        response = await handle_pipeline_await_request(
            payload=payload,
            service=_pipeline_readiness_service(state.get("pipeline_readiness")),
        )
        return JSONResponse(status_code=response.status_code, content=response.body)

    @app.get("/v1/control/{control_path:path}")
    async def control_get_route(control_path: str, request: Request) -> JSONResponse:
        response = await handle_control_http_request(
            method="GET",
            path=f"/v1/control/{control_path}",
            query=dict(request.query_params),
            payload={},
            services=_control_http_services(state),
        )
        return JSONResponse(status_code=response.status_code, content=response.body)

    @app.patch("/v1/control/{control_path:path}")
    async def control_patch_route(control_path: str, request: Request) -> JSONResponse:
        payload = await _json_payload(request)
        response = await handle_control_http_request(
            method="PATCH",
            path=f"/v1/control/{control_path}",
            query=dict(request.query_params),
            payload=payload,
            services=_control_http_services(state),
        )
        return JSONResponse(status_code=response.status_code, content=response.body)

    @app.post("/v1/control/{control_path:path}")
    async def control_post_route(control_path: str, request: Request) -> JSONResponse:
        payload = await _json_payload(request)
        response = await handle_control_http_request(
            method="POST",
            path=f"/v1/control/{control_path}",
            query=dict(request.query_params),
            payload=payload,
            services=_control_http_services(state),
        )
        return JSONResponse(status_code=response.status_code, content=response.body)

    @app.patch("/v1/memory/{memory_id}")
    async def memory_patch_route(memory_id: str, request: Request) -> JSONResponse:
        payload = await _json_payload(request)
        response = await handle_control_http_request(
            method="PATCH",
            path=f"/v1/memory/{memory_id}",
            query=dict(request.query_params),
            payload=payload,
            services=_control_http_services(state),
        )
        return JSONResponse(status_code=response.status_code, content=response.body)

    @app.post("/v1/memory/{memory_id}/{action}")
    async def memory_action_route(memory_id: str, action: str, request: Request) -> JSONResponse:
        payload = await _json_payload(request)
        response = await handle_control_http_request(
            method="POST",
            path=f"/v1/memory/{memory_id}/{action}",
            query=dict(request.query_params),
            payload=payload,
            services=_control_http_services(state),
        )
        return JSONResponse(status_code=response.status_code, content=response.body)

    @app.post("/v1/source-events/{source_event_id}/purge")
    async def source_purge_route(source_event_id: str, request: Request) -> JSONResponse:
        payload = await _json_payload(request)
        response = await handle_control_http_request(
            method="POST",
            path=f"/v1/source-events/{source_event_id}/purge",
            query=dict(request.query_params),
            payload=payload,
            services=_control_http_services(state),
        )
        return JSONResponse(status_code=response.status_code, content=response.body)

    @app.post("/v1/platforms/{platform}/push-candidates/{candidate_id}/send")
    async def platform_push_send_route(
        platform: str,
        candidate_id: str,
        request: Request,
    ) -> JSONResponse:
        payload = await _json_payload(request)
        response = await handle_control_http_request(
            method="POST",
            path=f"/v1/platforms/{platform}/push-candidates/{candidate_id}/send",
            query=dict(request.query_params),
            payload=payload,
            services=_control_http_services(state),
        )
        return JSONResponse(status_code=response.status_code, content=response.body)

    @app.post("/{path:path}")
    async def post_route(path: str, request: Request) -> JSONResponse:
        payload = await _json_payload(request)
        response = await handle_openclaw_http_request(
            method="POST",
            path=f"/{path}",
            payload=payload,
            runtime=_agent_runtime(state["runtime"]),
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


def _api_runtime_context(
    context: AgentRuntimePort | MemWingApiRuntimeContext,
) -> MemWingApiRuntimeContext:
    if isinstance(context, MemWingApiRuntimeContext):
        return context
    return MemWingApiRuntimeContext(runtime=context)


def _agent_runtime(value: object) -> AgentRuntimePort:
    if isinstance(value, AgentRuntimePort):
        return value
    raise TypeError("agent runtime has invalid type")


def _benchmark_admin_service(value: object) -> BenchmarkAdminService | None:
    if value is None or isinstance(value, BenchmarkAdminService):
        return value
    raise TypeError("benchmark admin service has invalid type")


def _pipeline_readiness_service(value: object) -> PipelineReadinessService:
    if isinstance(value, PipelineReadinessService):
        return value
    raise TypeError("pipeline readiness service is not configured")


def _control_http_services(
    state: Mapping[str, object],
) -> ControlHttpServices:
    control = state.get("control")
    scope_resolver = state.get("control_scope_resolver")
    source_redaction = state.get("source_redaction")
    if not isinstance(control, ControlService):
        raise TypeError("control service is not configured")
    if not isinstance(scope_resolver, ScopeResolver):
        raise TypeError("control scope resolver is not configured")
    if source_redaction is not None and not isinstance(source_redaction, SourceRedactionService):
        raise TypeError("source redaction service has invalid type")
    return ControlHttpServices(
        control=control,
        scope_resolver=scope_resolver,
        source_redaction=source_redaction,
    )


app = create_app()
