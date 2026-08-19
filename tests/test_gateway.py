import json
import tarfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from paply_gateway.app import create_app
from paply_gateway.auth import encode_access_token
from paply_gateway.models import load_models_template
from paply_gateway.settings import Settings

MODELS_TEMPLATE = """
schemaVersion: 2
meta:
  name: Test Gateway
chat:
  providers:
    - id: paply
      name: PaplyAI
      api: openai-responses
      models:
        - id: paply-chat
          input: [text]
vision: null
imageGen: null
"""


def make_settings(config_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "paply_environment": "development",
        "paply_litellm_url": "http://litellm.test",
        "paply_public_base_url": "https://gateway.paply.test",
        "paply_models_config_path": config_path,
        "paply_accounts_db_path": config_path.parent / "accounts.sqlite3",
        "paply_auth_jwt_secret": "test-paply-jwt-secret",
        "paply_auth_jwt_issuer": "paply-test",
        "paply_auth_jwt_audience": "paply-gateway-test",
        "paply_litellm_service_token": "test-internal-service-token",
        "litellm_master_key": "test-master-key",
        "paply_upstream_timeout_seconds": 10,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "models.yaml"
    path.write_text(MODELS_TEMPLATE, encoding="utf-8")
    return path


def access_token(user_id: str = "user-alice", *, expires_at: int = 4_000_000_000) -> str:
    return encode_access_token(
        user_id=user_id,
        secret="test-paply-jwt-secret",
        issuer="paply-test",
        audience="paply-gateway-test",
        issued_at=1_700_000_000,
        expires_at=expires_at,
    )


def test_models_config_requires_a_paply_session(config_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected upstream call: {request.url}")

    app = create_app(make_settings(config_path), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        response = client.get("/api/models")

    assert response.status_code == 401
    assert response.headers["x-request-id"]


def test_register_login_refresh_and_logout_create_no_client_key(config_path: Path) -> None:
    provisioned_users: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/user/new":
            assert request.headers["authorization"] == "Bearer test-master-key"
            payload = json.loads(request.content)
            assert payload["auto_create_key"] is False
            assert payload["user_email"] == "researcher@example.com"
            assert payload["models"] == ["paply-chat", "paply-vision", "paply-image"]
            provisioned_users.append(payload)
            return httpx.Response(200, json={"user_id": payload["user_id"], "token": None})
        raise AssertionError(f"unexpected upstream call: {request.url}")

    app = create_app(make_settings(config_path), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        registered = client.post(
            "/api/auth/register",
            json={
                "displayName": "论文研究员",
                "email": "Researcher@Example.com",
                "password": "correct-horse-battery-staple",
            },
        )
        assert registered.status_code == 200
        session = registered.json()
        assert session["user"]["email"] == "researcher@example.com"
        assert session["user"]["displayName"] == "论文研究员"
        assert session["accessToken"]
        assert session["refreshToken"]
        assert "key" not in json.dumps(session).lower()

        me = client.get(
            "/api/auth/me",
            headers={"authorization": f"Bearer {session['accessToken']}"},
        )
        assert me.status_code == 200
        assert me.json()["id"] == session["user"]["id"]

        refreshed = client.post(
            "/api/auth/refresh",
            json={"refreshToken": session["refreshToken"]},
        )
        assert refreshed.status_code == 200
        rotated = refreshed.json()
        assert rotated["refreshToken"] != session["refreshToken"]

        old_refresh = client.post(
            "/api/auth/refresh",
            json={"refreshToken": session["refreshToken"]},
        )
        assert old_refresh.status_code == 401

        logout = client.post(
            "/api/auth/logout",
            json={"refreshToken": rotated["refreshToken"]},
        )
        assert logout.status_code == 200
        after_logout = client.post(
            "/api/auth/refresh",
            json={"refreshToken": rotated["refreshToken"]},
        )
        assert after_logout.status_code == 401

        login = client.post(
            "/api/auth/login",
            json={
                "email": "researcher@example.com",
                "password": "correct-horse-battery-staple",
            },
        )
        assert login.status_code == 200

    assert len(provisioned_users) == 1
    assert provisioned_users[0]["user_id"].startswith("user_")


def test_registration_rejects_duplicate_email_and_invalid_login(config_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/user/new":
            return httpx.Response(200, json={"ok": True})
        raise AssertionError(f"unexpected upstream call: {request.url}")

    app = create_app(make_settings(config_path), transport=httpx.MockTransport(handler))
    payload = {
        "displayName": "测试用户",
        "email": "duplicate@example.com",
        "password": "correct-horse-battery-staple",
    }
    with TestClient(app) as client:
        assert client.post("/api/auth/register", json=payload).status_code == 200
        duplicate = client.post("/api/auth/register", json=payload)
        invalid_login = client.post(
            "/api/auth/login",
            json={"email": payload["email"], "password": "wrong-password"},
        )

    assert duplicate.status_code == 409
    assert invalid_login.status_code == 401


def test_models_config_contains_no_credentials(config_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected upstream call: {request.url}")

    app = create_app(make_settings(config_path), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        response = client.get(
            "/api/models",
            headers={"authorization": f"Bearer {access_token()}", "x-request-id": "request-1"},
        )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "request-1"
    document = response.json()
    assert document == {
        "schemaVersion": 2,
        "meta": {"name": "Test Gateway"},
        "chat": {
            "providers": [
                {
                    "id": "paply",
                    "name": "PaplyAI",
                    "api": "openai-responses",
                    "models": [{"id": "paply-chat", "input": ["text"]}],
                    "baseUrl": "https://gateway.paply.test/v1",
                }
            ]
        },
        "vision": None,
        "imageGen": None,
    }


def test_invalid_paply_session_is_rejected(config_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected upstream call: {request.url}")

    app = create_app(make_settings(config_path), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        response = client.get(
            "/api/models",
            headers={"authorization": "Bearer not-a-session"},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid Paply session token"


def test_expired_paply_session_is_rejected(config_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected upstream call: {request.url}")

    app = create_app(make_settings(config_path), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        response = client.get(
            "/api/models",
            headers={"authorization": f"Bearer {access_token(expires_at=1)}"},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Paply session has expired"


def test_proxy_preserves_streaming_body_status_and_maps_server_side_identity(
    config_path: Path,
) -> None:
    class ServerSentEvents(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"data: first\n\n"
            yield b"data: [DONE]\n\n"

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("http://litellm.test/v1/responses?include=usage")
        assert request.headers["authorization"] == "Bearer test-internal-service-token"
        assert request.headers["x-paply-user-id"] == "user-alice"
        assert request.headers["x-request-id"] == "stream-request"
        assert await request.aread() == b'{"model":"paply-chat","input":"hello"}'
        return httpx.Response(
            200,
            stream=ServerSentEvents(),
            headers={"content-type": "text/event-stream"},
        )

    app = create_app(make_settings(config_path), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        response = client.post(
            "/v1/responses?include=usage",
            content=b'{"model":"paply-chat","input":"hello"}',
            headers={
                "authorization": f"Bearer {access_token()}",
                "content-type": "application/json",
                "x-request-id": "stream-request",
                "x-paply-user-id": "attacker-controlled-user",
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-request-id"] == "stream-request"
    assert response.content == b"data: first\n\ndata: [DONE]\n\n"


def test_readiness_surfaces_litellm_failure(config_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"ok": False})

    app = create_app(make_settings(config_path), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"ok": False, "litellm": "status-503"}


def test_production_rejects_insecure_public_url(config_path: Path) -> None:
    with pytest.raises(ValidationError, match="must use HTTPS"):
        make_settings(
            config_path,
            paply_environment="production",
            paply_public_base_url="http://gateway.paply.test",
        )


def test_invalid_models_document_fails_at_startup(tmp_path: Path) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text("schemaVersion: 1\nchat: {providers: []}\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="violates the desktop contract"):
        create_app(make_settings(path))


def test_committed_models_template_matches_the_desktop_contract() -> None:
    template = load_models_template(Path("config/paply-models.yaml"))

    assert template.schema_version == 2
    assert template.chat.providers[0].models[0].thinking_levels[0] == "off"


def _write_skill_catalog(tmp_path: Path) -> Path:
    artifact = tmp_path / "skills" / "academic-pipeline"
    artifact.mkdir(parents=True)
    (artifact / "SKILL.md").write_text("# Academic pipeline\n", encoding="utf-8")
    (artifact / "guide.md").write_text("Research guide\n", encoding="utf-8")
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "skills": [
                    {
                        "id": "academic-pipeline",
                        "name": "科研全流程",
                        "description": "测试技能",
                        "version": "1.0.0",
                        "category": "research",
                        "downloadUrl": None,
                        "artifactPath": "skills/academic-pipeline",
                        "status": "available",
                    },
                    {
                        "id": "future-skill",
                        "name": "开发中技能",
                        "description": "尚未开放",
                        "category": "research",
                        "downloadUrl": None,
                        "status": "adapting",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return catalog


def test_skills_catalog_materializes_gateway_artifact_urls(
    config_path: Path,
    tmp_path: Path,
) -> None:
    catalog_path = _write_skill_catalog(tmp_path)
    app = create_app(
        make_settings(config_path, paply_skills_catalog_path=catalog_path)
    )

    with TestClient(app) as client:
        response = client.get("/api/skills")

    assert response.status_code == 200
    document = response.json()
    assert document["schemaVersion"] == 1
    assert document["skills"][0]["downloadUrl"] == (
        "https://gateway.paply.test/api/skills/academic-pipeline/artifact"
    )
    assert "artifactPath" not in document["skills"][0]
    assert document["skills"][1]["downloadUrl"] is None


def test_skill_artifact_is_a_client_compatible_gzip_archive(
    config_path: Path,
    tmp_path: Path,
) -> None:
    catalog_path = _write_skill_catalog(tmp_path)
    app = create_app(
        make_settings(config_path, paply_skills_catalog_path=catalog_path)
    )

    with TestClient(app) as client:
        response = client.get("/api/skills/academic-pipeline/artifact")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/gzip")
    archive_path = tmp_path / "download.tgz"
    archive_path.write_bytes(response.content)
    with tarfile.open(archive_path, "r:gz") as archive:
        names = archive.getnames()
    assert any(name.endswith("SKILL.md") for name in names)
    assert any(name.endswith("guide.md") for name in names)


def test_skills_endpoint_fails_closed_when_catalog_is_not_configured(
    config_path: Path,
) -> None:
    app = create_app(make_settings(config_path))

    with TestClient(app) as client:
        response = client.get("/api/skills")

    assert response.status_code == 503


def test_skill_artifact_cannot_escape_catalog_root(
    config_path: Path,
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "SKILL.md").write_text("# Outside\n", encoding="utf-8")
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "skills": [
                    {
                        "id": "outside-skill",
                        "name": "非法技能",
                        "description": "路径越界",
                        "category": "test",
                        "artifactPath": f"../{outside.name}",
                        "status": "available",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="skills catalog is invalid"):
        create_app(
            make_settings(config_path, paply_skills_catalog_path=catalog_path)
        )
