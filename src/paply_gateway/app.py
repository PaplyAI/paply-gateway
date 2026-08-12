import json
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import monotonic
from typing import Any
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from paply_gateway import __version__
from paply_gateway.models import ModelsTemplate, load_models_template
from paply_gateway.settings import Settings

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


def _bearer_token(request: Request, bootstrap_key: str | None) -> str:
    authorization = request.headers.get("authorization")
    if authorization:
        scheme, separator, token = authorization.partition(" ")
        if separator and scheme.lower() == "bearer" and token.strip():
            return token.strip()
        raise HTTPException(status_code=401, detail="Authorization must use a Bearer token")
    if bootstrap_key:
        return bootstrap_key
    raise HTTPException(status_code=401, detail="A PaplyAI virtual key is required")


def _forward_headers(headers: httpx.Headers) -> dict[str, str]:
    return {
        name: value
        for name, value in headers.items()
        if name.lower() not in HOP_BY_HOP_HEADERS and name.lower() != "content-length"
    }


async def _validate_virtual_key(
    client: httpx.AsyncClient,
    settings: Settings,
    token: str,
    request_id: str,
) -> None:
    try:
        response = await client.get(
            f"{settings.paply_litellm_url}/key/info",
            headers={
                "authorization": f"Bearer {token}",
                "x-request-id": request_id,
            },
        )
    except httpx.RequestError as error:
        raise HTTPException(
            status_code=503,
            detail="LiteLLM key validation is unavailable",
        ) from error
    if response.status_code in {401, 403, 404}:
        raise HTTPException(
            status_code=401,
            detail="The PaplyAI virtual key is invalid, expired, or not a virtual key",
        )
    if response.is_error:
        raise HTTPException(
            status_code=503,
            detail=f"LiteLLM key validation failed with status {response.status_code}",
        )


def create_app(
    settings: Settings | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    runtime_settings = settings or Settings()
    models_template: ModelsTemplate = load_models_template(
        runtime_settings.paply_models_config_path
    )

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
        token = _bearer_token(request, runtime_settings.bootstrap_key)
        client: httpx.AsyncClient = request.app.state.http_client
        await _validate_virtual_key(
            client,
            runtime_settings,
            token,
            request.state.request_id,
        )
        return models_template.materialize(
            base_url=runtime_settings.public_v1_base_url,
            api_key=token,
        )

    @application.api_route(
        "/v1/{upstream_path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    async def proxy_openai_route(upstream_path: str, request: Request) -> StreamingResponse:
        client: httpx.AsyncClient = request.app.state.http_client
        headers = {
            name: value
            for name, value in request.headers.items()
            if name.lower() not in HOP_BY_HOP_HEADERS
            and name.lower() not in {"host", "content-length"}
        }
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
