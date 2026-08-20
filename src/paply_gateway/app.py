import json
import logging
import os
import re
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import monotonic, time
from typing import Any
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from paply_gateway import __version__
from paply_gateway.accounts import (
    Account,
    AccountExistsError,
    AccountStore,
    InvalidCredentialsError,
    InvalidRefreshSessionError,
)
from paply_gateway.auth import (
    AccountDocument,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    SessionDocument,
    bearer_identity,
    encode_access_token,
)
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
AUTH_ATTEMPTS: dict[tuple[str, str], deque[float]] = defaultdict(deque)
AUTH_WINDOW_SECONDS = 300
AUTH_MAX_ATTEMPTS = 10


def _request_id(request: Request) -> str:
    candidate = request.headers.get("x-request-id", "")
    if REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return uuid4().hex


def _json_log(event: str, **fields: Any) -> None:
    LOGGER.info(json.dumps({"event": event, **fields}, separators=(",", ":"), sort_keys=True))


def _client_address(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _allow_auth_attempt(request: Request, action: str) -> bool:
    key = (_client_address(request), action)
    now = monotonic()
    attempts = AUTH_ATTEMPTS[key]
    while attempts and now - attempts[0] > AUTH_WINDOW_SECONDS:
        attempts.popleft()
    if len(attempts) >= AUTH_MAX_ATTEMPTS:
        return False
    attempts.append(now)
    return True


def _clear_auth_attempts(request: Request, action: str) -> None:
    AUTH_ATTEMPTS.pop((_client_address(request), action), None)


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
    account_store: AccountStore | None = None,
) -> FastAPI:
    runtime_settings = settings or Settings()
    models_template: ModelsTemplate = load_models_template(
        runtime_settings.paply_models_config_path
    )
    skills_catalog: SkillCatalog | None = None
    if runtime_settings.paply_skills_catalog_path is not None:
        skills_catalog = load_skill_catalog(runtime_settings.paply_skills_catalog_path)
    accounts = account_store or AccountStore(runtime_settings.paply_accounts_db_path)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        await accounts.initialize()
        timeout = httpx.Timeout(runtime_settings.paply_upstream_timeout_seconds, connect=10.0)
        application.state.http_client = httpx.AsyncClient(
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )
        application.state.account_store = accounts
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
            await accounts.ping()
        except Exception as error:
            _json_log("accounts_readiness_failed", error_type=type(error).__name__)
            return JSONResponse(
                status_code=503,
                content={"ok": False, "accounts": "unavailable"},
            )
        try:
            response = await client.get(
                f"{runtime_settings.paply_litellm_url}/v1/models",
                headers={
                    "authorization": f"Bearer {runtime_settings.litellm_service_token}",
                    "x-paply-user-id": "paply-readiness",
                    "x-request-id": request.state.request_id,
                },
            )
        except httpx.RequestError:
            return JSONResponse(status_code=503, content={"ok": False, "litellm": "unreachable"})
        if response.is_error:
            return JSONResponse(
                status_code=503,
                content={"ok": False, "litellm": f"status-{response.status_code}"},
            )
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            _json_log("litellm_models_readiness_invalid", request_id=request.state.request_id)
            return JSONResponse(
                status_code=503,
                content={"ok": False, "litellm": "invalid-models-response"},
            )
        available_models = {
            item.get("id")
            for item in payload["data"]
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        missing_models = sorted(models_template.required_model_ids() - available_models)
        if missing_models:
            _json_log(
                "litellm_models_readiness_missing",
                request_id=request.state.request_id,
                missing_models=missing_models,
            )
            return JSONResponse(
                status_code=503,
                content={
                    "ok": False,
                    "litellm": "models-unavailable",
                    "missingModels": missing_models,
                },
            )
        return JSONResponse(content={"ok": True, "litellm": "ready"})

    def session_document(
        account: Account,
        refresh_token: str,
        *,
        issued_at: int,
    ) -> SessionDocument:
        access_token_expires_at = issued_at + runtime_settings.paply_auth_access_token_seconds
        return SessionDocument(
            accessToken=encode_access_token(
                user_id=account.id,
                secret=runtime_settings.auth_jwt_secret,
                issuer=runtime_settings.paply_auth_jwt_issuer,
                audience=runtime_settings.paply_auth_jwt_audience,
                issued_at=issued_at,
                expires_at=access_token_expires_at,
            ),
            accessTokenExpiresAt=access_token_expires_at,
            refreshToken=refresh_token,
            user=AccountDocument.from_account(account),
        )

    async def provision_litellm_user(
        request: Request,
        account: Account,
    ) -> None:
        client: httpx.AsyncClient = request.app.state.http_client
        try:
            response = await client.post(
                f"{runtime_settings.paply_litellm_url}/user/new",
                headers={
                    "authorization": f"Bearer {runtime_settings.master_key}",
                    "content-type": "application/json",
                    "x-request-id": request.state.request_id,
                },
                json={
                    "auto_create_key": False,
                    "budget_duration": runtime_settings.paply_default_user_budget_duration,
                    "max_budget": runtime_settings.paply_default_user_budget,
                    "metadata": {"provisioned_by": "paply-account-registration"},
                    "models": ["paply-chat", "paply-vision", "paply-image"],
                    "user_alias": account.display_name,
                    "user_email": account.email,
                    "user_id": account.id,
                    "user_role": "internal_user",
                },
            )
        except httpx.RequestError as error:
            raise HTTPException(
                status_code=503,
                detail="Usage account provisioning is unavailable",
            ) from error
        if response.is_error:
            _json_log(
                "litellm_user_provision_failed",
                request_id=request.state.request_id,
                status_code=response.status_code,
            )
            raise HTTPException(
                status_code=503,
                detail="Usage account provisioning failed",
            )

    @application.post("/api/auth/register", response_model=SessionDocument)
    async def register(payload: RegisterRequest, request: Request) -> SessionDocument:
        if not _allow_auth_attempt(request, "register"):
            raise HTTPException(status_code=429, detail="Too many registration attempts")
        user_id = f"user_{uuid4().hex}"
        try:
            account = await accounts.create_account(
                user_id=user_id,
                email=payload.email,
                display_name=payload.display_name,
                password=payload.password,
            )
        except AccountExistsError as error:
            raise HTTPException(status_code=409, detail="Account already exists") from error
        try:
            await provision_litellm_user(request, account)
        except Exception:
            await accounts.delete_account(account.id)
            raise
        now = int(time())
        refresh_token = await accounts.create_refresh_session(
            account.id,
            expires_at=now + runtime_settings.paply_auth_refresh_token_seconds,
        )
        _clear_auth_attempts(request, "register")
        _json_log("account_registered", request_id=request.state.request_id, user_id=account.id)
        return session_document(account, refresh_token, issued_at=now)

    @application.post("/api/auth/login", response_model=SessionDocument)
    async def login(payload: LoginRequest, request: Request) -> SessionDocument:
        if not _allow_auth_attempt(request, "login"):
            raise HTTPException(status_code=429, detail="Too many login attempts")
        try:
            account = await accounts.authenticate(payload.email, payload.password)
        except InvalidCredentialsError as error:
            raise HTTPException(status_code=401, detail="Invalid email or password") from error
        now = int(time())
        refresh_token = await accounts.create_refresh_session(
            account.id,
            expires_at=now + runtime_settings.paply_auth_refresh_token_seconds,
        )
        _clear_auth_attempts(request, "login")
        _json_log(
            "account_login_succeeded",
            request_id=request.state.request_id,
            user_id=account.id,
        )
        return session_document(account, refresh_token, issued_at=now)

    @application.post("/api/auth/refresh", response_model=SessionDocument)
    async def refresh(payload: RefreshRequest, request: Request) -> SessionDocument:
        now = int(time())
        try:
            account, refresh_token = await accounts.rotate_refresh_session(
                payload.refresh_token,
                expires_at=now + runtime_settings.paply_auth_refresh_token_seconds,
            )
        except InvalidRefreshSessionError as error:
            raise HTTPException(status_code=401, detail="Refresh session is invalid") from error
        _json_log(
            "account_session_refreshed",
            request_id=request.state.request_id,
            user_id=account.id,
        )
        return session_document(account, refresh_token, issued_at=now)

    @application.post("/api/auth/logout")
    async def logout(payload: LogoutRequest, request: Request) -> dict[str, bool]:
        await accounts.revoke_refresh_session(payload.refresh_token)
        _json_log("account_logout", request_id=request.state.request_id)
        return {"ok": True}

    @application.get("/api/auth/me", response_model=AccountDocument)
    async def current_account(request: Request) -> AccountDocument:
        identity = bearer_identity(request, runtime_settings)
        account = await accounts.account(identity.user_id)
        if account is None:
            raise HTTPException(status_code=401, detail="Paply account no longer exists")
        return AccountDocument.from_account(account)

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
