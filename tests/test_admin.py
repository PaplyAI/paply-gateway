import json
import re
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient

from paplyai_gateway.admin import create_admin_app
from paplyai_gateway.settings import Settings


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
        paplyai_gateway_internal_url="http://gateway.test",
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


def login(client: TestClient) -> str:
    response = client.post(
        "/api/admin/session",
        json={"username": "paply_test", "password": "test-admin-password"},
    )
    assert response.status_code == 200
    document = response.json()["data"]
    assert document["authenticated"] is True
    return str(document["csrf_token"])


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
                            "api_key": "provider-secret-must-never-render",
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


def test_spa_shell_is_public_but_admin_api_requires_session(tmp_path: Path) -> None:
    app = create_admin_app(
        admin_settings(tmp_path),
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )
    with TestClient(app) as client:
        for path in ("/", "/overview", "/users", "/models", "/system", "/login"):
            response = client.get(path)
            assert response.status_code == 200
            assert "PaplyAI Gateway" in response.text
            assert "/static/admin-app/" in response.text
        session = client.get("/api/admin/session")
        protected = client.get("/api/admin/overview")

    assert session.json() == {"data": {"authenticated": False}}
    assert protected.status_code == 401


def test_admin_static_assets_are_compressed_and_cacheable(tmp_path: Path) -> None:
    app = create_admin_app(
        admin_settings(tmp_path),
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )
    with TestClient(app) as client:
        shell = client.get("/login")
        asset_match = re.search(r'(/static/admin-app/assets/[^"\']+\.js)', shell.text)
        assert asset_match is not None
        asset = client.get(asset_match.group(1), headers={"accept-encoding": "gzip"})
        logo = client.get("/static/admin-app/paplyai-logo.png")

    assert asset.status_code == 200
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert asset.headers["content-encoding"] == "gzip"
    assert logo.headers["cache-control"] == "public, max-age=86400"


def test_invalid_admin_credentials_are_visible_without_secret_echo(tmp_path: Path) -> None:
    app = create_admin_app(
        admin_settings(tmp_path),
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/admin/session",
            json={"username": "paply_test", "password": "wrong-password"},
        )

    assert response.status_code == 401
    assert "账号或密码不正确" in response.json()["detail"]
    assert "wrong-password" not in response.text


def test_session_and_overview_api_do_not_expose_credentials(tmp_path: Path) -> None:
    app = create_admin_app(
        admin_settings(tmp_path),
        transport=httpx.MockTransport(overview_handler),
    )
    with TestClient(app) as client:
        csrf = login(client)
        session = client.get("/api/admin/session")
        overview = client.get("/api/admin/overview")

    assert session.status_code == overview.status_code == 200
    assert session.json()["data"]["csrf_token"] == csrf
    assert session.json()["data"]["allowed_models"] == [
        "paply-chat",
        "paply-image",
        "paply-vision",
    ]
    data = overview.json()["data"]
    assert data["total_tokens"] == "125,000"
    assert data["model_group_count"] == 1
    assert data["deployment_count"] == 2
    assert "test-master-key" not in overview.text
    assert "provider-secret-must-never-render" not in overview.text


def test_users_and_models_api_return_control_plane_data_only(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return overview_handler(request)

    app = create_admin_app(admin_settings(tmp_path), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        login(client)
        users = client.get("/api/admin/users")
        models = client.get("/api/admin/models")

    assert users.status_code == models.status_code == 200
    assert users.json()["data"]["users"][0]["alias"] == "论文测试账号"
    group = models.json()["data"]["groups"][0]
    assert group["name"] == "paply-chat"
    assert group["deployment_count"] == 2
    assert group["deployments"][0]["provider"] in {"api.deepseek.test", "aliyun.test"}
    assert "api_key" not in models.text
    assert "provider-secret-must-never-render" not in models.text
    assert "test-master-key" not in models.text


def test_system_api_checks_gateway_and_litellm(tmp_path: Path) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"ok": True})

    app = create_admin_app(admin_settings(tmp_path), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        login(client)
        response = client.get("/api/admin/system")

    assert response.status_code == 200
    assert response.json()["data"]["healthy"] is True
    assert len(seen) == 4
    assert "http://gateway.test/health/ready" in seen
    assert "http://litellm.test/health/readiness" in seen


def test_create_deployment_requires_csrf_and_sends_write_only_key(tmp_path: Path) -> None:
    created: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/model/new"
        created.update(json.loads(request.content))
        return httpx.Response(200, json={"message": "created"})

    payload = {
        "model_name": "paply-chat",
        "upstream_model": "openai/deepseek-v4-flash",
        "api_base": "https://provider.test/v1/",
        "api_key": "provider-secret",
        "weight": "2",
        "rpm": "60",
        "tpm": "12000",
    }
    app = create_admin_app(admin_settings(tmp_path), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        csrf = login(client)
        rejected = client.post("/api/admin/deployments", json=payload)
        response = client.post(
            "/api/admin/deployments",
            json=payload,
            headers={"X-CSRF-Token": csrf},
        )

    assert rejected.status_code == 403
    assert response.status_code == 200
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


def test_model_mutations_and_health_use_deployment_id(tmp_path: Path) -> None:
    calls: list[tuple[str, str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        calls.append((request.method, request.url.path, body))
        return httpx.Response(200, json={"healthy_endpoints": ["deployment-one"]})

    app = create_admin_app(admin_settings(tmp_path), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        csrf = login(client)
        headers = {"X-CSRF-Token": csrf}
        toggle = client.patch(
            "/api/admin/deployments/deployment-one/state",
            json={"blocked": True},
            headers=headers,
        )
        tested = client.post(
            "/api/admin/deployments/deployment-one/test",
            headers=headers,
        )
        deleted = client.delete(
            "/api/admin/deployments/deployment-one",
            headers=headers,
        )

    assert toggle.status_code == tested.status_code == deleted.status_code == 200
    assert (
        "POST",
        "/model/update",
        {"model_info": {"id": "deployment-one"}, "blocked": True},
    ) in calls
    assert any(method == "GET" and path == "/health" for method, path, _ in calls)
    assert ("POST", "/model/delete", {"id": "deployment-one"}) in calls


def test_health_result_uses_litellm_endpoint_lists_without_leaking_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        return httpx.Response(
            200,
            json={
                "healthy_endpoints": [],
                "unhealthy_endpoints": [
                    {"model_id": "deployment-one", "error": "provider-secret"}
                ],
            },
        )

    app = create_admin_app(admin_settings(tmp_path), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        csrf = login(client)
        response = client.post(
            "/api/admin/deployments/deployment-one/test",
            headers={"X-CSRF-Token": csrf},
        )

    assert response.status_code == 200
    assert response.json()["data"]["health"]["state"] == "unhealthy"
    assert response.json()["data"]["health"]["label"] == "上游检查失败"
    assert "provider-secret" not in response.text


def test_update_user_budget_is_csrf_protected(tmp_path: Path) -> None:
    payloads: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/user/update"
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"user_id": "user_test"})

    payload = {
        "max_budget": "25",
        "budget_duration": "30d",
        "rpm_limit": "20",
        "tpm_limit": "",
        "max_parallel_requests": "3",
        "blocked": False,
    }
    app = create_admin_app(admin_settings(tmp_path), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        csrf = login(client)
        rejected = client.patch("/api/admin/users/user_test", json=payload)
        response = client.patch(
            "/api/admin/users/user_test",
            json=payload,
            headers={"X-CSRF-Token": csrf},
        )

    assert rejected.status_code == 403
    assert response.status_code == 200
    assert payloads == [
        {
            "user_id": "user_test",
            "max_budget": 25.0,
            "budget_duration": "30d",
            "rpm_limit": 20,
            "tpm_limit": None,
            "max_parallel_requests": 3,
            "blocked": False,
        }
    ]


def test_logout_requires_csrf_and_clears_session(tmp_path: Path) -> None:
    app = create_admin_app(
        admin_settings(tmp_path),
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )
    with TestClient(app) as client:
        csrf = login(client)
        rejected = client.delete("/api/admin/session")
        response = client.delete(
            "/api/admin/session",
            headers={"X-CSRF-Token": csrf},
        )
        protected = client.get("/api/admin/overview")

    assert rejected.status_code == 403
    assert response.status_code == 200
    assert response.json() == {"data": {"authenticated": False}}
    assert protected.status_code == 401
