import json
import logging
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import monotonic
from typing import Any
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from paply_gateway import __version__
from paply_gateway.auth import bearer_identity
from paply_gateway.models import ModelsTemplate, load_models_template
from paply_gateway.settings import Settings
from paply_gateway.skills import SkillCatalog, create_skill_archive, load_skill_catalog

LOGGER = logging.getLogger("paply.gateway")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


def _request_id(request: Request) -> str:
    candidate = request.headers.get("x-request-id", "")
    if REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return uuid4().hex


def _json_log(event: str, **fields: Any) -> None:
    LOGGER.info(json.dumps({"event": event, **fields}, separators=(",", ":"), sort_keys=True))


def _forward_headers(headers: httpx.Headers) -> dict[str, str]:
    return {
        name: value
        for name, value in headers.items()
        if name.lower() not in HOP_BY_HOP_HEADERS and name.lower() != "content-length"
    }


def create_app(
    settings: Settings | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    runtime_settings = settings or Settings()
    models_template: ModelsTemplate = load_models_template(
        runtime_settings.paply_models_config_path
    )
    skills_catalog: SkillCatalog | None = None
    if runtime_settings.paply_skills_catalog_path is not None:
        skills_catalog = load_skill_catalog(runtime_settings.paply_skills_catalog_path)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        timeout = httpx.Timeout(runtime_settings.paply_upstream_timeout_seconds, connect=10.0)
        application.state.http_client = httpx.AsyncClient(
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )
        _json_log(
            "gateway_started",
            environment=runtime_settings.paply_environment,
            version=__version__,
        )
        try:
            yield
        finally:
            await application.state.http_client.aclose()
            _json_log("gateway_stopped")

    application = FastAPI(
        title="Paply Token Gateway",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @application.middleware("http")
    async def request_observability(request: Request, call_next: Any) -> Any:
        request_id = _request_id(request)
        request.state.request_id = request_id
        started = monotonic()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["x-request-id"] = request_id
            return response
        finally:
            _json_log(
                "request_completed",
                duration_ms=round((monotonic() - started) * 1000, 2),
                method=request.method,
                path=request.url.path,
                request_id=request_id,
                status_code=status_code,
            )

    @application.get("/")
    async def root() -> dict[str, str]:
        return {"name": "paply-token-gateway", "version": __version__}

    @application.get("/health/live")
    async def liveness() -> dict[str, bool]:
        return {"ok": True}

    @application.get("/health/ready")
    async def readiness(request: Request) -> JSONResponse:
        client: httpx.AsyncClient = request.app.state.http_client
        try:
            response = await client.get(
                f"{runtime_settings.paply_litellm_url}/health/liveliness",
                headers={"x-request-id": request.state.request_id},
            )
        except httpx.RequestError:
            return JSONResponse(status_code=503, content={"ok": False, "litellm": "unreachable"})
        if response.is_error:
            return JSONResponse(
                status_code=503,
                content={"ok": False, "litellm": f"status-{response.status_code}"},
            )
        return JSONResponse(content={"ok": True, "litellm": "ready"})

    @application.get("/api/models")
    async def models_config(request: Request) -> dict[str, object]:
        bearer_identity(request, runtime_settings)
        return models_template.materialize(base_url=runtime_settings.public_v1_base_url)

    @application.get("/api/skills")
    async def skills_config() -> dict[str, object]:
        if skills_catalog is None:
            raise HTTPException(
                status_code=503,
                detail="PaplyAI skill catalog is not configured",
            )
        return skills_catalog.public_document(runtime_settings.paply_public_base_url)

    @application.get("/api/skills/{skill_id}/artifact")
    async def skill_artifact(skill_id: str) -> FileResponse:
        if skills_catalog is None:
            raise HTTPException(
                status_code=503,
                detail="PaplyAI skill catalog is not configured",
            )
        skill = skills_catalog.skill(skill_id)
        if skill is None or skill.status != "available" or not skill.artifact_path:
            raise HTTPException(
                status_code=404,
                detail="PaplyAI skill artifact was not found",
            )
        try:
            archive = create_skill_archive(skills_catalog, skill)
        except (OSError, ValueError) as error:
            _json_log(
                "skill_artifact_failed",
                skill_id=skill_id,
                error_type=type(error).__name__,
            )
            raise HTTPException(
                status_code=503,
                detail="PaplyAI skill artifact is unavailable",
            ) from error
        return FileResponse(
            archive,
            media_type="application/gzip",
            filename=f"{skill.id}-{skill.version}.tar.gz",
            background=BackgroundTask(os.unlink, archive),
        )

    @application.api_route(
        "/v1/{upstream_path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    async def proxy_openai_route(upstream_path: str, request: Request) -> StreamingResponse:
        identity = bearer_identity(request, runtime_settings)
        client: httpx.AsyncClient = request.app.state.http_client
        headers = {
            name: value
            for name, value in request.headers.items()
            if name.lower() not in HOP_BY_HOP_HEADERS
            and name.lower()
            not in {
                "host",
                "content-length",
                "authorization",
                "x-paply-user-id",
                "x-paply-service",
            }
        }
        headers["authorization"] = f"Bearer {runtime_settings.litellm_service_token}"
        headers["x-paply-user-id"] = identity.user_id
        headers["x-request-id"] = request.state.request_id
        upstream_request = client.build_request(
            request.method,
            f"{runtime_settings.paply_litellm_url}/v1/{upstream_path}",
            headers=headers,
            content=request.stream(),
            params=request.query_params.multi_items(),
        )
        try:
            upstream_response = await client.send(upstream_request, stream=True)
        except httpx.RequestError as error:
            raise HTTPException(status_code=502, detail="LiteLLM request failed") from error
        return StreamingResponse(
            upstream_response.aiter_raw(),
            status_code=upstream_response.status_code,
            headers=_forward_headers(upstream_response.headers),
            background=BackgroundTask(upstream_response.aclose),
        )

    return application
