import asyncio
import hmac
import logging
import re
import secrets
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from paply_gateway import __version__
from paply_gateway.models import load_models_template
from paply_gateway.settings import Settings

LOGGER = logging.getLogger("paply.admin")
WEB_ROOT = Path("web").resolve()
LOGIN_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)
LOGIN_WINDOW_SECONDS = 300
LOGIN_MAX_ATTEMPTS = 5
DEPLOYMENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
MODEL_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9_./:-]{1,200}$")
BUDGET_DURATION_PATTERN = re.compile(r"^[1-9][0-9]*(?:s|m|h|d|mo)$")


class AdminInputError(ValueError):
    """An operator input failed local validation before reaching LiteLLM."""


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


def _format_count(value: Any) -> str:
    try:
        return f"{int(value or 0):,}"
    except (TypeError, ValueError):
        return "0"


async def _litellm_json(
    client: httpx.AsyncClient,
    settings: Settings,
    path: str,
    *,
    params: list[tuple[str, str]] | None = None,
    method: str = "GET",
    json_body: dict[str, Any] | None = None,
) -> Any:
    response = await client.request(
        method,
        f"{settings.paply_litellm_url}{path}",
        params=params,
        json=json_body,
        headers={"authorization": f"Bearer {settings.master_key}"},
    )
    response.raise_for_status()
    return response.json()


def _csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not isinstance(token, str) or len(token) < 32:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def _verify_csrf(request: Request, submitted: str) -> None:
    expected = request.session.get("csrf_token")
    if not isinstance(expected, str) or not hmac.compare_digest(expected, submitted):
        raise AdminInputError("页面已过期，请刷新后重试。")


def _set_flash(request: Request, message: str, level: str = "success") -> None:
    request.session["flash"] = {"message": message, "level": level}


def _take_flash(request: Request) -> dict[str, str] | None:
    flash = request.session.pop("flash", None)
    if not isinstance(flash, dict):
        return None
    message = flash.get("message")
    level = flash.get("level")
    if not isinstance(message, str) or level not in {"success", "error"}:
        return None
    return {"message": message, "level": level}


def _positive_number(value: str, label: str, *, integer: bool = False) -> int | float | None:
    normalized = value.strip()
    if not normalized:
        return None
    try:
        parsed: int | float = int(normalized) if integer else float(normalized)
    except ValueError as error:
        raise AdminInputError(f"{label}必须是数字。") from error
    if parsed <= 0:
        raise AdminInputError(f"{label}必须大于 0。")
    return parsed


def _validated_deployment_id(value: str) -> str:
    normalized = value.strip()
    if not DEPLOYMENT_ID_PATTERN.fullmatch(normalized):
        raise AdminInputError("模型节点 ID 不合法。")
    return normalized


def _validated_model_value(value: str, label: str) -> str:
    normalized = value.strip()
    if not MODEL_VALUE_PATTERN.fullmatch(normalized):
        raise AdminInputError(f"{label}格式不合法。")
    return normalized


def _validated_public_model(value: str, allowed_models: set[str]) -> str:
    normalized = _validated_model_value(value, "公开模型名称")
    if normalized not in allowed_models:
        raise AdminInputError("公开模型名称不在 PaplyAI 下发协议中。")
    return normalized


def _validated_api_base(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise AdminInputError("API Base 必须是无凭据、查询参数和片段的 HTTP(S) 地址。")
    return normalized


def _optional_limit(value: str, label: str) -> int | None:
    parsed = _positive_number(value, label, integer=True)
    return int(parsed) if parsed is not None else None


def _deployment_mode(model_name: str) -> str:
    return "image_generation" if model_name == "paply-image" else "chat"


def _deployment_params(
    *,
    upstream_model: str,
    api_base: str,
    api_key: str,
    weight: str,
    rpm: str,
    tpm: str,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "model": _validated_model_value(upstream_model, "上游模型"),
        "api_base": _validated_api_base(api_base),
    }
    if api_key.strip():
        params["api_key"] = api_key.strip()
    parsed_weight = _positive_number(weight, "权重")
    parsed_rpm = _optional_limit(rpm, "RPM")
    parsed_tpm = _optional_limit(tpm, "TPM")
    if parsed_weight is not None:
        params["weight"] = parsed_weight
    if parsed_rpm is not None:
        params["rpm"] = parsed_rpm
    if parsed_tpm is not None:
        params["tpm"] = parsed_tpm
    return params


def _user_rows(document: Any) -> list[dict[str, Any]]:
    rows = document.get("users", []) if isinstance(document, dict) else []
    users: list[dict[str, Any]] = []
    for info in rows:
        if not isinstance(info, dict) or info.get("user_role") == "proxy_admin":
            continue
        spend = float(info.get("spend") or 0)
        budget = float(info.get("max_budget") or 0)
        users.append(
            {
                "alias": info.get("user_alias") or info.get("user_email") or "未命名用户",
                "user_id": info.get("user_id") or "未知用户",
                "spend": _format_money(spend),
                "spend_value": spend,
                "budget": _format_money(budget),
                "budget_value": budget,
                "budget_percent": min(100, round((spend / budget) * 100, 1)) if budget else 0,
                "models": info.get("models") or [],
                "duration": info.get("budget_duration") or "30d",
                "role": info.get("user_role") or "internal_user",
                "rpm_limit": info.get("rpm_limit") or "",
                "tpm_limit": info.get("tpm_limit") or "",
                "max_parallel_requests": info.get("max_parallel_requests") or "",
                "blocked": bool(info.get("blocked")),
            }
        )
    return users


def _health_timestamp() -> str:
    return datetime.now(UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _health_endpoint_matches(endpoint: Any, deployment_id: str) -> bool:
    if isinstance(endpoint, str):
        return endpoint == deployment_id
    if not isinstance(endpoint, dict):
        return False
    model_info = endpoint.get("model_info")
    nested_id = model_info.get("id") if isinstance(model_info, dict) else None
    return endpoint.get("model_id") == deployment_id or nested_id == deployment_id


def _deployment_health_result(document: Any, deployment_id: str) -> dict[str, str]:
    checked_at = _health_timestamp()
    if not isinstance(document, dict):
        return {"state": "unknown", "label": "结果不可识别", "checked_at": checked_at}
    healthy = document.get("healthy_endpoints")
    unhealthy = document.get("unhealthy_endpoints")
    healthy_rows = healthy if isinstance(healthy, list) else []
    unhealthy_rows = unhealthy if isinstance(unhealthy, list) else []
    if any(_health_endpoint_matches(row, deployment_id) for row in unhealthy_rows):
        return {"state": "unhealthy", "label": "上游检查失败", "checked_at": checked_at}
    if any(_health_endpoint_matches(row, deployment_id) for row in healthy_rows):
        return {"state": "healthy", "label": "节点健康", "checked_at": checked_at}
    return {"state": "unknown", "label": "未返回目标节点", "checked_at": checked_at}


async def _check_deployment_health(
    client: httpx.AsyncClient,
    settings: Settings,
    deployment_id: str,
) -> dict[str, str]:
    result = await _litellm_json(
        client,
        settings,
        "/health",
        params=[("model_id", deployment_id)],
    )
    return _deployment_health_result(result, deployment_id)


def _model_groups(
    document: Any,
    health_by_id: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    rows = document.get("data", []) if isinstance(document, dict) else []
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in rows:
        if not isinstance(item, dict):
            continue
        params = item.get("litellm_params") or {}
        info = item.get("model_info") or {}
        deployment_id = str(info.get("id") or "")
        if not deployment_id:
            continue
        api_base = str(params.get("api_base") or "")
        hostname = urlparse(api_base).hostname or "未配置地址"
        health = (health_by_id or {}).get(
            deployment_id,
            {"state": "unknown", "label": "尚未检测", "checked_at": ""},
        )
        groups[str(item.get("model_name") or "未知模型")].append(
            {
                "id": deployment_id,
                "name": item.get("model_name") or "未知模型",
                "upstream": params.get("model") or "未配置",
                "api_base": api_base,
                "provider": hostname,
                "weight": params.get("weight") or "",
                "rpm": params.get("rpm") or "",
                "tpm": params.get("tpm") or "",
                "mode": info.get("mode") or _deployment_mode(str(item.get("model_name") or "")),
                "blocked": bool(item.get("blocked") or info.get("blocked")),
                "db_model": info.get("db_model") is True,
                "health": health,
            }
        )
    return [
        {
            "name": name,
            "deployments": sorted(deployments, key=lambda row: (row["blocked"], row["provider"])),
            "deployment_count": len(deployments),
            "active_count": sum(not row["blocked"] for row in deployments),
        }
        for name, deployments in sorted(groups.items())
    ]


async def _users_data(client: httpx.AsyncClient, settings: Settings) -> dict[str, Any]:
    result = await _litellm_json(
        client,
        settings,
        "/user/list",
        params=[("page", "1"), ("page_size", "100"), ("sort_by", "spend"), ("sort_order", "desc")],
    )
    users = _user_rows(result)
    return {
        "users": users,
        "user_count": len(users),
        "total_budget": _format_money(sum(row["budget_value"] for row in users)),
        "total_spend": _format_money(sum(row["spend_value"] for row in users)),
    }


async def _models_data(
    client: httpx.AsyncClient,
    settings: Settings,
    health_by_id: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    result = await _litellm_json(client, settings, "/model/info")
    groups = _model_groups(result, health_by_id)
    return {
        "groups": groups,
        "group_count": len(groups),
        "deployment_count": sum(group["deployment_count"] for group in groups),
        "active_count": sum(group["active_count"] for group in groups),
    }


async def _dashboard_data(client: httpx.AsyncClient, settings: Settings) -> dict[str, Any]:
    end_date = date.today()
    start_date = end_date - timedelta(days=29)
    spend_result, user_list_result, model_result, activity_result = await asyncio.gather(
        _litellm_json(client, settings, "/global/spend"),
        _litellm_json(
            client,
            settings,
            "/user/list",
            params=[
                ("page", "1"),
                ("page_size", "100"),
                ("sort_by", "spend"),
                ("sort_order", "desc"),
            ],
        ),
        _litellm_json(client, settings, "/model/info"),
        _litellm_json(
            client,
            settings,
            "/user/daily/activity",
            params=[
                ("start_date", start_date.isoformat()),
                ("end_date", end_date.isoformat()),
                ("page", "1"),
                ("page_size", "100"),
            ],
        ),
    )
    users = _user_rows(user_list_result)
    model_groups = _model_groups(model_result)
    total_spend = spend_result.get("spend") if isinstance(spend_result, dict) else 0
    total_budget = sum(row["budget_value"] for row in users)
    activity_metadata = (
        activity_result.get("metadata", {}) if isinstance(activity_result, dict) else {}
    )
    return {
        "total_spend": _format_money(total_spend),
        "total_budget": _format_money(total_budget),
        "user_count": len(users),
        "model_group_count": len(model_groups),
        "deployment_count": sum(group["deployment_count"] for group in model_groups),
        "total_tokens": _format_count(activity_metadata.get("total_tokens")),
        "prompt_tokens": _format_count(activity_metadata.get("total_prompt_tokens")),
        "completion_tokens": _format_count(
            activity_metadata.get("total_completion_tokens")
        ),
        "request_count": _format_count(activity_metadata.get("total_api_requests")),
        "successful_request_count": _format_count(
            activity_metadata.get("total_successful_requests")
        ),
        "failed_request_count": _format_count(
            activity_metadata.get("total_failed_requests")
        ),
        "activity_period": f"{start_date.isoformat()} 至 {end_date.isoformat()}",
        "users": users[:5],
        "model_groups": model_groups,
        "updated_at": datetime.now(UTC).astimezone().strftime("%Y年%m月%d日 %H:%M:%S"),
    }


async def _probe(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    started = monotonic()
    try:
        response = await client.get(url, headers=headers)
        healthy = 200 <= response.status_code < 300
        return {
            "healthy": healthy,
            "status": response.status_code,
            "latency_ms": round((monotonic() - started) * 1000),
        }
    except httpx.RequestError:
        return {
            "healthy": False,
            "status": "不可达",
            "latency_ms": round((monotonic() - started) * 1000),
        }


async def _system_data(client: httpx.AsyncClient, settings: Settings) -> dict[str, Any]:
    authorization = {"authorization": f"Bearer {settings.master_key}"}
    probes = await asyncio.gather(
        _probe(client, f"{settings.paply_gateway_internal_url}/health/live"),
        _probe(client, f"{settings.paply_gateway_internal_url}/health/ready"),
        _probe(client, f"{settings.paply_litellm_url}/health/liveliness"),
        _probe(
            client,
            f"{settings.paply_litellm_url}/health/readiness",
            headers=authorization,
        ),
    )
    components = [
        {"name": "Paply Gateway 进程", "description": "产品 API 与身份边界", **probes[0]},
        {"name": "Paply Gateway 就绪", "description": "账户库与公开模型协议", **probes[1]},
        {"name": "LiteLLM 进程", "description": "模型数据面", **probes[2]},
        {"name": "LiteLLM 就绪", "description": "PostgreSQL 与路由依赖", **probes[3]},
    ]
    return {
        "components": components,
        "healthy": all(component["healthy"] for component in components),
        "updated_at": datetime.now(UTC).astimezone().strftime("%Y年%m月%d日 %H:%M:%S"),
    }


def create_admin_app(
    settings: Settings | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    runtime_settings = settings or Settings()
    allowed_models = load_models_template(
        runtime_settings.paply_models_config_path
    ).required_model_ids()
    if not runtime_settings.paply_admin_username:
        raise RuntimeError("PAPLY_ADMIN_USERNAME is required for the Paply admin application")
    admin_password = runtime_settings.admin_password
    admin_session_secret = runtime_settings.admin_session_secret
    if not all((admin_password, admin_session_secret, runtime_settings.master_key)):
        raise RuntimeError("Paply admin secrets must not be empty")

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.deployment_health = {}
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
        title="Paply Gateway 管理中心",
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

    def page_context(
        request: Request,
        *,
        active_page: str,
        data: dict[str, Any] | None,
        error: str | None = None,
    ) -> dict[str, Any]:
        return {
            "active_page": active_page,
            "allowed_models": sorted(allowed_models),
            "csrf_token": _csrf_token(request),
            "data": data,
            "error": error,
            "flash": _take_flash(request),
            "litellm_ui_url": runtime_settings.paply_litellm_ui_public_url,
            "username": runtime_settings.paply_admin_username,
            "version": __version__,
        }

    async def render_data_page(
        request: Request,
        *,
        template_name: str,
        active_page: str,
        loader: Any,
        failure_message: str,
    ) -> Any:
        if not _is_authenticated(request):
            return RedirectResponse("/login", status_code=303)
        try:
            data = await loader(request.app.state.http_client, runtime_settings)
            context = page_context(request, active_page=active_page, data=data)
            return templates.TemplateResponse(request, template_name, context)
        except (httpx.RequestError, httpx.HTTPStatusError) as error:
            LOGGER.error(
                "admin_page_upstream_failed",
                extra={"page": active_page, "error_type": type(error).__name__},
            )
            context = page_context(
                request,
                active_page=active_page,
                data=None,
                error=failure_message,
            )
            return templates.TemplateResponse(
                request,
                template_name,
                context,
                status_code=503,
            )

    def mutation_error(
        request: Request,
        *,
        target: str,
        event: str,
        error: Exception,
    ) -> RedirectResponse:
        if isinstance(error, AdminInputError):
            message = str(error)
        else:
            message = "LiteLLM 未接受本次操作，请检查节点状态后重试。"
            LOGGER.error(
                event,
                extra={"error_type": type(error).__name__},
            )
        _set_flash(request, message, "error")
        return RedirectResponse(target, status_code=303)

    @application.get("/health/live")
    async def liveness() -> dict[str, bool]:
        return {"ok": True}

    @application.get("/", response_class=HTMLResponse)
    async def home(request: Request) -> Any:
        if not _is_authenticated(request):
            return RedirectResponse("/login", status_code=303)
        return RedirectResponse("/overview", status_code=303)

    @application.get("/overview", response_class=HTMLResponse)
    async def overview_page(request: Request) -> Any:
        return await render_data_page(
            request,
            template_name="overview.html",
            active_page="overview",
            loader=_dashboard_data,
            failure_message="暂时无法读取网关概览，请检查 LiteLLM 后重试。",
        )

    @application.get("/users", response_class=HTMLResponse)
    async def users_page(request: Request) -> Any:
        return await render_data_page(
            request,
            template_name="users.html",
            active_page="users",
            loader=_users_data,
            failure_message="暂时无法读取用户预算，请检查 LiteLLM 后重试。",
        )

    @application.get("/models", response_class=HTMLResponse)
    async def models_page(request: Request) -> Any:
        async def load_models(
            client: httpx.AsyncClient,
            settings: Settings,
        ) -> dict[str, Any]:
            return await _models_data(
                client,
                settings,
                request.app.state.deployment_health,
            )

        return await render_data_page(
            request,
            template_name="models.html",
            active_page="models",
            loader=load_models,
            failure_message="暂时无法读取模型节点，请检查 LiteLLM 后重试。",
        )

    @application.get("/system", response_class=HTMLResponse)
    async def system_page(request: Request) -> Any:
        return await render_data_page(
            request,
            template_name="system.html",
            active_page="system",
            loader=_system_data,
            failure_message="暂时无法读取系统状态。",
        )

    @application.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request) -> Any:
        if _is_authenticated(request):
            return RedirectResponse("/overview", status_code=303)
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
        _csrf_token(request)
        return RedirectResponse("/overview", status_code=303)

    @application.post("/users/{user_id}/budget")
    async def update_user_budget(
        request: Request,
        user_id: str,
        csrf_token: str = Form(...),
        max_budget: str = Form(...),
        budget_duration: str = Form(...),
        rpm_limit: str = Form(""),
        tpm_limit: str = Form(""),
        max_parallel_requests: str = Form(""),
        blocked: bool = Form(False),
    ) -> RedirectResponse:
        if not _is_authenticated(request):
            return RedirectResponse("/login", status_code=303)
        try:
            _verify_csrf(request, csrf_token)
            normalized_user_id = _validated_model_value(user_id, "用户标识")
            parsed_budget = _positive_number(max_budget, "预算")
            duration = budget_duration.strip()
            if not BUDGET_DURATION_PATTERN.fullmatch(duration):
                raise AdminInputError("预算周期格式应类似 30d 或 1mo。")
            payload: dict[str, Any] = {
                "user_id": normalized_user_id,
                "max_budget": parsed_budget,
                "budget_duration": duration,
                "rpm_limit": _optional_limit(rpm_limit, "RPM"),
                "tpm_limit": _optional_limit(tpm_limit, "TPM"),
                "max_parallel_requests": _optional_limit(
                    max_parallel_requests,
                    "最大并发数",
                ),
                "blocked": blocked,
            }
            await _litellm_json(
                request.app.state.http_client,
                runtime_settings,
                "/user/update",
                method="POST",
                json_body=payload,
            )
            LOGGER.info("admin_user_budget_updated")
            _set_flash(request, "用户预算与限额已更新。")
        except (AdminInputError, httpx.RequestError, httpx.HTTPStatusError) as error:
            return mutation_error(
                request,
                target="/users",
                event="admin_user_budget_update_failed",
                error=error,
            )
        return RedirectResponse("/users", status_code=303)

    @application.post("/models/deployments")
    async def create_deployment(
        request: Request,
        csrf_token: str = Form(...),
        model_name: str = Form(...),
        upstream_model: str = Form(...),
        api_base: str = Form(...),
        api_key: str = Form(...),
        weight: str = Form(""),
        rpm: str = Form(""),
        tpm: str = Form(""),
    ) -> RedirectResponse:
        if not _is_authenticated(request):
            return RedirectResponse("/login", status_code=303)
        try:
            _verify_csrf(request, csrf_token)
            public_model = _validated_public_model(model_name, allowed_models)
            if not api_key.strip():
                raise AdminInputError("新节点必须填写 API Key。")
            deployment_id = str(uuid4())
            payload = {
                "model_name": public_model,
                "litellm_params": _deployment_params(
                    upstream_model=upstream_model,
                    api_base=api_base,
                    api_key=api_key,
                    weight=weight,
                    rpm=rpm,
                    tpm=tpm,
                ),
                "model_info": {
                    "id": deployment_id,
                    "mode": _deployment_mode(public_model),
                },
            }
            await _litellm_json(
                request.app.state.http_client,
                runtime_settings,
                "/model/new",
                method="POST",
                json_body=payload,
            )
            LOGGER.info("admin_model_deployment_created")
            _set_flash(request, "模型节点已创建并加入负载均衡池。")
        except (AdminInputError, httpx.RequestError, httpx.HTTPStatusError) as error:
            return mutation_error(
                request,
                target="/models",
                event="admin_model_deployment_create_failed",
                error=error,
            )
        return RedirectResponse("/models", status_code=303)

    @application.post("/models/deployments/{deployment_id}/update")
    async def update_deployment(
        request: Request,
        deployment_id: str,
        csrf_token: str = Form(...),
        model_name: str = Form(...),
        upstream_model: str = Form(...),
        api_base: str = Form(...),
        api_key: str = Form(""),
        weight: str = Form(""),
        rpm: str = Form(""),
        tpm: str = Form(""),
    ) -> RedirectResponse:
        if not _is_authenticated(request):
            return RedirectResponse("/login", status_code=303)
        try:
            _verify_csrf(request, csrf_token)
            normalized_id = _validated_deployment_id(deployment_id)
            public_model = _validated_public_model(model_name, allowed_models)
            params = _deployment_params(
                upstream_model=upstream_model,
                api_base=api_base,
                api_key=api_key,
                weight=weight,
                rpm=rpm,
                tpm=tpm,
            )
            if not weight.strip():
                params["weight"] = None
            if not rpm.strip():
                params["rpm"] = None
            if not tpm.strip():
                params["tpm"] = None
            payload = {
                "model_name": public_model,
                "litellm_params": params,
                "model_info": {
                    "id": normalized_id,
                    "mode": _deployment_mode(public_model),
                },
            }
            await _litellm_json(
                request.app.state.http_client,
                runtime_settings,
                "/model/update",
                method="POST",
                json_body=payload,
            )
            request.app.state.deployment_health.pop(normalized_id, None)
            LOGGER.info("admin_model_deployment_updated")
            _set_flash(request, "模型节点配置已更新。")
        except (AdminInputError, httpx.RequestError, httpx.HTTPStatusError) as error:
            return mutation_error(
                request,
                target="/models",
                event="admin_model_deployment_update_failed",
                error=error,
            )
        return RedirectResponse("/models", status_code=303)

    @application.post("/models/deployments/{deployment_id}/toggle")
    async def toggle_deployment(
        request: Request,
        deployment_id: str,
        csrf_token: str = Form(...),
        blocked: bool = Form(...),
    ) -> RedirectResponse:
        if not _is_authenticated(request):
            return RedirectResponse("/login", status_code=303)
        try:
            _verify_csrf(request, csrf_token)
            normalized_id = _validated_deployment_id(deployment_id)
            await _litellm_json(
                request.app.state.http_client,
                runtime_settings,
                "/model/update",
                method="POST",
                json_body={"model_info": {"id": normalized_id}, "blocked": blocked},
            )
            request.app.state.deployment_health.pop(normalized_id, None)
            LOGGER.info("admin_model_deployment_state_updated")
            _set_flash(request, "模型节点状态已更新。")
        except (AdminInputError, httpx.RequestError, httpx.HTTPStatusError) as error:
            return mutation_error(
                request,
                target="/models",
                event="admin_model_deployment_toggle_failed",
                error=error,
            )
        return RedirectResponse("/models", status_code=303)

    @application.post("/models/deployments/{deployment_id}/test")
    async def test_deployment(
        request: Request,
        deployment_id: str,
        csrf_token: str = Form(...),
    ) -> RedirectResponse:
        if not _is_authenticated(request):
            return RedirectResponse("/login", status_code=303)
        normalized_id: str | None = None
        try:
            _verify_csrf(request, csrf_token)
            normalized_id = _validated_deployment_id(deployment_id)
            health = await _check_deployment_health(
                request.app.state.http_client,
                runtime_settings,
                normalized_id,
            )
            request.app.state.deployment_health[normalized_id] = health
            LOGGER.info("admin_model_deployment_tested")
            if health["state"] != "healthy":
                _set_flash(request, f"节点检测未通过：{health['label']}。", "error")
            else:
                _set_flash(request, "节点连接测试完成，上游健康。")
        except (AdminInputError, httpx.RequestError, httpx.HTTPStatusError) as error:
            if normalized_id and not isinstance(error, AdminInputError):
                request.app.state.deployment_health[normalized_id] = {
                    "state": "unknown",
                    "label": "健康检查不可达",
                    "checked_at": _health_timestamp(),
                }
            return mutation_error(
                request,
                target="/models",
                event="admin_model_deployment_test_failed",
                error=error,
            )
        return RedirectResponse("/models", status_code=303)

    @application.post("/models/health/refresh")
    async def refresh_deployment_health(
        request: Request,
        csrf_token: str = Form(...),
    ) -> RedirectResponse:
        if not _is_authenticated(request):
            return RedirectResponse("/login", status_code=303)
        try:
            _verify_csrf(request, csrf_token)
            model_document = await _litellm_json(
                request.app.state.http_client,
                runtime_settings,
                "/model/info",
            )
            groups = _model_groups(model_document)
            deployment_ids = [
                node["id"]
                for group in groups
                for node in group["deployments"]
                if not node["blocked"]
            ]
            results = await asyncio.gather(
                *(
                    _check_deployment_health(
                        request.app.state.http_client,
                        runtime_settings,
                        deployment_id,
                    )
                    for deployment_id in deployment_ids
                ),
                return_exceptions=True,
            )
            counts = {"healthy": 0, "unhealthy": 0, "unknown": 0}
            for deployment_id, result in zip(deployment_ids, results, strict=True):
                if isinstance(result, BaseException):
                    health = {
                        "state": "unknown",
                        "label": "健康检查不可达",
                        "checked_at": _health_timestamp(),
                    }
                    LOGGER.error(
                        "admin_model_deployment_health_failed",
                        extra={"error_type": type(result).__name__},
                    )
                else:
                    health = result
                request.app.state.deployment_health[deployment_id] = health
                counts[health["state"]] += 1
            level = "success" if counts["unhealthy"] == counts["unknown"] == 0 else "error"
            _set_flash(
                request,
                "节点健康刷新完成："
                f"{counts['healthy']} 个健康，{counts['unhealthy']} 个异常，"
                f"{counts['unknown']} 个未知。",
                level,
            )
            LOGGER.info("admin_model_deployment_health_refreshed")
        except (AdminInputError, httpx.RequestError, httpx.HTTPStatusError) as error:
            return mutation_error(
                request,
                target="/models",
                event="admin_model_deployment_health_refresh_failed",
                error=error,
            )
        return RedirectResponse("/models", status_code=303)

    @application.post("/models/deployments/{deployment_id}/delete")
    async def delete_deployment(
        request: Request,
        deployment_id: str,
        csrf_token: str = Form(...),
    ) -> RedirectResponse:
        if not _is_authenticated(request):
            return RedirectResponse("/login", status_code=303)
        try:
            _verify_csrf(request, csrf_token)
            normalized_id = _validated_deployment_id(deployment_id)
            await _litellm_json(
                request.app.state.http_client,
                runtime_settings,
                "/model/delete",
                method="POST",
                json_body={"id": normalized_id},
            )
            request.app.state.deployment_health.pop(normalized_id, None)
            LOGGER.info("admin_model_deployment_deleted")
            _set_flash(request, "模型节点已删除。")
        except (AdminInputError, httpx.RequestError, httpx.HTTPStatusError) as error:
            return mutation_error(
                request,
                target="/models",
                event="admin_model_deployment_delete_failed",
                error=error,
            )
        return RedirectResponse("/models", status_code=303)

    @application.post("/logout")
    async def logout(
        request: Request,
        csrf_token: str = Form(...),
    ) -> RedirectResponse:
        if not _is_authenticated(request):
            return RedirectResponse("/login", status_code=303)
        try:
            _verify_csrf(request, csrf_token)
        except AdminInputError:
            return RedirectResponse("/overview", status_code=303)
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    return application
