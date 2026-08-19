from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from paply_gateway.admin import create_admin_app
from paply_gateway.settings import Settings


def admin_settings(tmp_path: Path) -> Settings:
    config = tmp_path / "models.yaml"
    config.write_text(
        "schemaVersion: 2\nchat: {providers: []}\nvision: null\nimageGen: null\n",
        encoding="utf-8",
    )
    return Settings(
        paply_environment="development",
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


def test_unauthenticated_admin_redirects_to_chinese_login(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected upstream call: {request.url}")

    app = create_admin_app(admin_settings(tmp_path), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        response = client.get("/", follow_redirects=False)
        login = client.get("/login")

    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert login.status_code == 200
    assert "欢迎回来" in login.text
    assert "管理员账号" in login.text


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


def test_admin_login_renders_usage_dashboard_without_exposing_master_key(
    tmp_path: Path,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-master-key"
        if request.url.path == "/global/spend":
            return httpx.Response(200, json={"spend": 1.25, "max_budget": 0})
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
                    ],
                    "total": 1,
                    "page": 1,
                    "page_size": 100,
                    "total_pages": 1,
                },
            )
        if request.url.path == "/model/info":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "model_name": "paply-chat",
                            "litellm_params": {"model": "openai/gpt-5-mini"},
                        }
                    ]
                },
            )
        if request.url.path == "/user/daily/activity":
            assert request.url.params["start_date"]
            assert request.url.params["end_date"]
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

    app = create_admin_app(
        admin_settings(tmp_path),
        transport=httpx.MockTransport(handler),
    )
    with TestClient(app) as client:
        login = client.post(
            "/login",
            data={"username": "paply_test", "password": "test-admin-password"},
            follow_redirects=False,
        )
        dashboard = client.get("/")

    assert login.status_code == 303
    assert dashboard.status_code == 200
    assert "用量概览" in dashboard.text
    assert "论文测试账号" in dashboard.text
    assert "$1.2500" in dashboard.text
    assert "125,000" in dashboard.text
    assert "输入 100,000 · 输出 25,000" in dashboard.text
    assert "成功 46 · 失败 2" in dashboard.text
    assert "test-master-key" not in dashboard.text
    assert 'href="http://litellm-ui.test:4000/ui"' in dashboard.text


def test_logout_clears_admin_session(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/global/spend":
            return httpx.Response(200, json={"spend": 0})
        if request.url.path == "/user/list":
            return httpx.Response(200, json={"users": [], "total": 0})
        if request.url.path == "/model/info":
            return httpx.Response(200, json={"data": []})
        if request.url.path == "/user/daily/activity":
            return httpx.Response(200, json={"results": [], "metadata": {}})
        raise AssertionError(f"unexpected upstream call: {request.url}")

    app = create_admin_app(admin_settings(tmp_path), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        client.post(
            "/login",
            data={"username": "paply_test", "password": "test-admin-password"},
        )
        logout = client.post("/logout", follow_redirects=False)
        dashboard = client.get("/", follow_redirects=False)

    assert logout.status_code == 303
    assert dashboard.status_code == 303
    assert dashboard.headers["location"] == "/login"
