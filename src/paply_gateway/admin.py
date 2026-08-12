import asyncio
import hmac
import logging
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import Any

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from paply_gateway import __version__
from paply_gateway.settings import Settings

LOGGER = logging.getLogger("paply.admin")
WEB_ROOT = Path("web").resolve()
LOGIN_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)
LOGIN_WINDOW_SECONDS = 300
LOGIN_MAX_ATTEMPTS = 5


def _client_address(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _allow_login_attempt(address: str) -> bool:
    now = monotonic()
    attempts = LOGIN_ATTEMPTS[address]
    while attempts and now - attempts[0] > LOGIN_WINDOW_SECONDS:
        attempts.popleft()
    if len(attempts) >= LOGIN_MAX_ATTEMPTS:
        return False
    attempts.append(now)
    return True


def _clear_login_attempts(address: str) -> None:
    LOGIN_ATTEMPTS.pop(address, None)


def _is_authenticated(request: Request) -> bool:
    return request.session.get("admin_authenticated") is True


def _format_money(value: Any) -> str:
    try:
        return f"${float(value or 0):,.4f}"
    except (TypeError, ValueError):
        return "$0.0000"


async def _litellm_json(
    client: httpx.AsyncClient,
    settings: Settings,
    path: str,
    *,
    params: list[tuple[str, str]] | None = None,
) -> Any:
    response = await client.get(
        f"{settings.paply_litellm_url}{path}",
        params=params,
        headers={"authorization": f"Bearer {settings.master_key}"},
    )
    response.raise_for_status()
    return response.json()


async def _dashboard_data(client: httpx.AsyncClient, settings: Settings) -> dict[str, Any]:
    spend_result, key_list_result, model_result = await asyncio.gather(
        _litellm_json(client, settings, "/global/spend"),
        _litellm_json(client, settings, "/key/list", params=[("page", "1"), ("size", "50")]),
        _litellm_json(client, settings, "/model/info"),
    )
    key_hashes = key_list_result.get("keys", []) if isinstance(key_list_result, dict) else []
    key_results = await asyncio.gather(
        *(
            _litellm_json(client, settings, "/key/info", params=[("key", key_hash)])
            for key_hash in key_hashes
        )
    )
    keys = []
    for result in key_results:
        info = result.get("info", {}) if isinstance(result, dict) else {}
        spend = float(info.get("spend") or 0)
        budget = float(info.get("max_budget") or 0)
        keys.append(
            {
                "alias": info.get("key_alias") or "未命名密钥",
                "user_id": info.get("user_id") or "未绑定用户",
                "spend": _format_money(spend),
                "budget": _format_money(budget),
                "budget_percent": min(100, round((spend / budget) * 100, 1)) if budget else 0,
                "models": info.get("models") or [],
                "duration": info.get("budget_duration") or "未设置",
                "blocked": bool(info.get("blocked")),
            }
        )
    model_data = model_result.get("data", []) if isinstance(model_result, dict) else []
    models = [
        {
            "name": item.get("model_name") or "未知模型",
            "upstream": (item.get("litellm_params") or {}).get("model") or "未配置",
        }
        for item in model_data
        if isinstance(item, dict)
    ]
    total_spend = spend_result.get("spend") if isinstance(spend_result, dict) else 0
    total_budget = sum(
        float((result.get("info") or {}).get("max_budget") or 0)
        for result in key_results
    )
    return {
        "total_spend": _format_money(total_spend),
        "total_budget": _format_money(total_budget),
        "key_count": len(keys),
        "model_count": len(models),
        "keys": keys,
        "models": models,
        "updated_at": datetime.now(UTC).astimezone().strftime("%Y年%m月%d日 %H:%M:%S"),
    }


def create_admin_app(
    settings: Settings | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    runtime_settings = settings or Settings()
    if not runtime_settings.paply_admin_username:
        raise RuntimeError("PAPLY_ADMIN_USERNAME is required for the Paply admin application")
    admin_password = runtime_settings.admin_password
    admin_session_secret = runtime_settings.admin_session_secret
    if not all((admin_password, admin_session_secret, runtime_settings.master_key)):
        raise RuntimeError("Paply admin secrets must not be empty")

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(20.0, connect=5.0),
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )
        try:
            yield
        finally:
            await application.state.http_client.aclose()

    application = FastAPI(
        title="PaplyAI 用量管理台",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.add_middleware(
        SessionMiddleware,
        secret_key=admin_session_secret,
        session_cookie="paply_admin_session",
        max_age=int(timedelta(hours=8).total_seconds()),
        same_site="strict",
        https_only=runtime_settings.paply_environment == "production",
    )
    application.mount("/static", StaticFiles(directory=WEB_ROOT / "static"), name="static")
    templates = Jinja2Templates(directory=WEB_ROOT / "templates")

    @application.get("/health/live")
    async def liveness() -> dict[str, bool]:
        return {"ok": True}

    @application.get("/", response_class=HTMLResponse)
    async def home(request: Request) -> Any:
        if not _is_authenticated(request):
            return RedirectResponse("/login", status_code=303)
        try:
            data = await _dashboard_data(request.app.state.http_client, runtime_settings)
            return templates.TemplateResponse(
                request,
                "dashboard.html",
                {
                    "data": data,
                    "username": runtime_settings.paply_admin_username,
                    "version": __version__,
                },
            )
        except (httpx.RequestError, httpx.HTTPStatusError) as error:
            LOGGER.error(
                "admin_dashboard_upstream_failed",
                extra={"error_type": type(error).__name__},
            )
            return templates.TemplateResponse(
                request,
                "dashboard.html",
                {
                    "data": None,
                    "username": runtime_settings.paply_admin_username,
                    "version": __version__,
                    "error": "暂时无法读取 LiteLLM 用量数据，请检查服务状态后重试。",
                },
                status_code=503,
            )

    @application.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request) -> Any:
        if _is_authenticated(request):
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse(request, "login.html", {"error": None})

    @application.post("/login", response_class=HTMLResponse)
    async def login(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
    ) -> Any:
        address = _client_address(request)
        if not _allow_login_attempt(address):
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "登录尝试过多，请五分钟后再试。"},
                status_code=429,
            )
        username_valid = hmac.compare_digest(
            username.strip(), runtime_settings.paply_admin_username
        )
        password_valid = hmac.compare_digest(password, admin_password)
        if not username_valid or not password_valid:
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "账号或密码不正确，请重新输入。"},
                status_code=401,
            )
        _clear_login_attempts(address)
        request.session.clear()
        request.session["admin_authenticated"] = True
        return RedirectResponse("/", status_code=303)

    @application.post("/logout")
    async def logout(request: Request) -> RedirectResponse:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    return application
