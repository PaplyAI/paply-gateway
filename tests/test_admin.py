import json
import re
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient

from paply_gateway.admin import create_admin_app
from paply_gateway.settings import Settings


def admin_settings(tmp_path: Path) -> Settings:
    config = tmp_path / "models.yaml"
    config.write_text(
        """schemaVersion: 2
chat:
  providers:
    - id: paply
      name: Paply
      api: openai-responses
      models:
        - id: paply-chat
          input: [text]
vision:
  provider: paply-vision
  apiType: openai-responses
  modelId: paply-vision
imageGen:
  provider: paply-image
  apiType: openai-images
  modelId: paply-image
""",
        encoding="utf-8",
    )
    return Settings(
        paply_environment="development",
        paply_gateway_internal_url="http://gateway.test",
        paply_litellm_url="http://litellm.test",
        paply_litellm_ui_public_url="http://litellm-ui.test:4000",
        paply_public_base_url="http://gateway.test",
        paply_models_config_path=config,
        paply_admin_username="paply_test",
        paply_admin_password="test-admin-password",
        paply_admin_session_secret="test-session-secret-with-sufficient-length",
        litellm_master_key="test-master-key",
        _env_file=None,
    )


def login(client: TestClient) -> None:
    response = client.post(
        "/login",
        data={"username": "paply_test", "password": "test-admin-password"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/overview"


def csrf_from(document: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', document)
    assert match
    return match.group(1)


def overview_handler(request: httpx.Request) -> httpx.Response:
    assert request.headers["authorization"] == "Bearer test-master-key"
    if request.url.path == "/global/spend":
        return httpx.Response(200, json={"spend": 1.25})
    if request.url.path == "/user/list":
        return httpx.Response(
            200,
            json={
                "users": [
                    {
                        "user_alias": "论文测试账号",
                        "user_id": "user_test",
                        "user_role": "internal_user",
                        "spend": 1.25,
                        "max_budget": 20,
                        "models": ["paply-chat"],
                        "budget_duration": "30d",
                    }
                ]
            },
        )
    if request.url.path == "/model/info":
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "model_name": "paply-chat",
                        "litellm_params": {
                            "model": "openai/deepseek-v4-flash",
                            "api_base": "https://api.deepseek.test/v1",
                        },
                        "model_info": {"id": "deployment-one", "db_model": True},
                    },
                    {
                        "model_name": "paply-chat",
                        "litellm_params": {
                            "model": "openai/deepseek-v4-flash",
                            "api_base": "https://aliyun.test/v1",
                        },
                        "model_info": {"id": "deployment-two", "db_model": True},
                    },
                ]
            },
        )
    if request.url.path == "/user/daily/activity":
        return httpx.Response(
            200,
            json={
                "results": [],
                "metadata": {
                    "total_tokens": 125000,
                    "total_prompt_tokens": 100000,
                    "total_completion_tokens": 25000,
                    "total_api_requests": 48,
                    "total_successful_requests": 46,
                    "total_failed_requests": 2,
                },
            },
        )
    raise AssertionError(f"unexpected upstream call: {request.url}")


def test_unauthenticated_pages_redirect_to_login(tmp_path: Path) -> None:
    app = create_admin_app(
        admin_settings(tmp_path),
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )
    with TestClient(app) as client:
        for path in ("/", "/overview", "/users", "/models", "/system"):
            response = client.get(path, follow_redirects=False)
            assert response.status_code == 303
            assert response.headers["location"] == "/login"
        login_page = client.get("/login")

    assert login_page.status_code == 200
    assert "Paply Gateway" in login_page.text
    assert "管理员账号" in login_page.text


def test_invalid_admin_credentials_are_visible(tmp_path: Path) -> None:
    app = create_admin_app(
        admin_settings(tmp_path),
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )
    with TestClient(app) as client:
        response = client.post(
            "/login",
            data={"username": "paply_test", "password": "wrong-password"},
        )

    assert response.status_code == 401
    assert "账号或密码不正确" in response.text


def test_overview_is_a_distinct_page_and_does_not_expose_master_key(tmp_path: Path) -> None:
    app = create_admin_app(
        admin_settings(tmp_path),
        transport=httpx.MockTransport(overview_handler),
    )
    with TestClient(app) as client:
        login(client)
        root = client.get("/", follow_redirects=False)
        page = client.get("/overview")

    assert root.status_code == 303
    assert root.headers["location"] == "/overview"
    assert page.status_code == 200
    assert "运行概览" in page.text
    assert "125,000" in page.text
    assert "1 / 2" in page.text
    assert 'href="/users"' in page.text
    assert 'href="/models"' in page.text
    assert 'href="#users"' not in page.text
    assert "test-master-key" not in page.text


def test_users_page_has_budget_controls(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/user/list"
        return overview_handler(request)

    app = create_admin_app(admin_settings(tmp_path), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        login(client)
        page = client.get("/users")

    assert page.status_code == 200
    assert "用户与预算" in page.text
    assert "论文测试账号" in page.text
    assert "最大并发" in page.text
    assert "test-master-key" not in page.text


def test_models_page_groups_deployments_without_exposing_credentials(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/model/info"
        return overview_handler(request)

    app = create_admin_app(admin_settings(tmp_path), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        login(client)
        page = client.get("/models")

    assert page.status_code == 200
    assert "模型与节点" in page.text
    assert "paply-chat" in page.text
    assert "api.deepseek.test" in page.text
    assert "aliyun.test" in page.text
    assert "新增节点" in page.text
    assert "simple-shuffle" in page.text
    assert "test-master-key" not in page.text


def test_system_page_checks_gateway_and_litellm(tmp_path: Path) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"ok": True})

    app = create_admin_app(admin_settings(tmp_path), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        login(client)
        page = client.get("/system")

    assert page.status_code == 200
    assert "系统状态" in page.text
    assert "全部正常" in page.text
    assert len(seen) == 4
    assert "http://gateway.test/health/ready" in seen
    assert "http://litellm.test/health/readiness" in seen


def test_create_deployment_validates_csrf_and_sends_write_only_key(tmp_path: Path) -> None:
    created: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/model/info":
            return httpx.Response(200, json={"data": []})
        if request.url.path == "/model/new":
            created.update(json.loads(request.content))
            return httpx.Response(200, json={"message": "created"})
        raise AssertionError(f"unexpected upstream call: {request.url}")

    app = create_admin_app(admin_settings(tmp_path), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        login(client)
        models = client.get("/models")
        csrf = csrf_from(models.text)
        response = client.post(
            "/models/deployments",
            data={
                "csrf_token": csrf,
                "model_name": "paply-chat",
                "upstream_model": "openai/deepseek-v4-flash",
                "api_base": "https://provider.test/v1/",
                "api_key": "provider-secret",
                "weight": "2",
                "rpm": "60",
                "tpm": "12000",
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/models"
    assert created["model_name"] == "paply-chat"
    assert created["litellm_params"] == {
        "model": "openai/deepseek-v4-flash",
        "api_base": "https://provider.test/v1",
        "api_key": "provider-secret",
        "weight": 2.0,
        "rpm": 60,
        "tpm": 12000,
    }
    assert created["model_info"]["mode"] == "chat"
    assert "provider-secret" not in response.text


def test_model_mutations_and_connection_test_use_deployment_id(tmp_path: Path) -> None:
    calls: list[tuple[str, str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        calls.append((request.method, request.url.path, body))
        return httpx.Response(200, json={"healthy_endpoints": ["deployment-one"]})

    app = create_admin_app(admin_settings(tmp_path), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        login(client)
        page = client.get("/models")
        csrf = csrf_from(page.text)
        toggle = client.post(
            "/models/deployments/deployment-one/toggle",
            data={"csrf_token": csrf, "blocked": "true"},
            follow_redirects=False,
        )
        test = client.post(
            "/models/deployments/deployment-one/test",
            data={"csrf_token": csrf},
            follow_redirects=False,
        )
        delete = client.post(
            "/models/deployments/deployment-one/delete",
            data={"csrf_token": csrf},
            follow_redirects=False,
        )

    assert toggle.status_code == test.status_code == delete.status_code == 303
    assert (
        "POST",
        "/model/update",
        {"model_info": {"id": "deployment-one"}, "blocked": True},
    ) in calls
    assert any(method == "GET" and path == "/health" for method, path, _ in calls)
    assert ("POST", "/model/delete", {"id": "deployment-one"}) in calls


def test_update_user_budget_is_csrf_protected(tmp_path: Path) -> None:
    payloads: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/user/list":
            return overview_handler(request)
        if request.url.path == "/user/update":
            payloads.append(json.loads(request.content))
            return httpx.Response(200, json={"user_id": "user_test"})
        raise AssertionError(f"unexpected upstream call: {request.url}")

    app = create_admin_app(admin_settings(tmp_path), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        login(client)
        page = client.get("/users")
        csrf = csrf_from(page.text)
        rejected = client.post(
            "/users/user_test/budget",
            data={"csrf_token": "invalid", "max_budget": "25", "budget_duration": "30d"},
            follow_redirects=False,
        )
        accepted = client.post(
            "/users/user_test/budget",
            data={
                "csrf_token": csrf,
                "max_budget": "25",
                "budget_duration": "30d",
                "rpm_limit": "30",
                "tpm_limit": "6000",
                "max_parallel_requests": "2",
                "blocked": "false",
            },
            follow_redirects=False,
        )

    assert rejected.status_code == accepted.status_code == 303
    assert len(payloads) == 1
    assert payloads[0]["user_id"] == "user_test"
    assert payloads[0]["max_budget"] == 25.0
    assert payloads[0]["rpm_limit"] == 30
    assert payloads[0]["tpm_limit"] == 6000


def test_logout_requires_csrf_and_clears_session(tmp_path: Path) -> None:
    app = create_admin_app(
        admin_settings(tmp_path),
        transport=httpx.MockTransport(overview_handler),
    )
    with TestClient(app) as client:
        login(client)
        page = client.get("/overview")
        csrf = csrf_from(page.text)
        logout = client.post(
            "/logout",
            data={"csrf_token": csrf},
            follow_redirects=False,
        )
        protected = client.get("/overview", follow_redirects=False)

    assert logout.status_code == 303
    assert protected.status_code == 303
    assert protected.headers["location"] == "/login"
