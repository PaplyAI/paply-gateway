from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from paply_gateway.app import create_app
from paply_gateway.models import load_models_template
from paply_gateway.settings import Settings

MODELS_TEMPLATE = """
schemaVersion: 1
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
        "paply_models_bootstrap_key": None,
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


def test_models_config_requires_a_virtual_key(config_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected upstream call: {request.url}")

    app = create_app(make_settings(config_path), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        response = client.get("/api/models")

    assert response.status_code == 401
    assert response.headers["x-request-id"]


def test_models_config_validates_and_returns_the_callers_key(config_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("http://litellm.test/key/info")
        if request.headers.get("authorization") == "Bearer test-key-user-alice":
            return httpx.Response(200, json={"key": "test-key-user-alice", "info": {}})
        return httpx.Response(401, json={"error": "invalid key"})

    app = create_app(make_settings(config_path), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        response = client.get(
            "/api/models",
            headers={"authorization": "Bearer test-key-user-alice", "x-request-id": "request-1"},
        )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "request-1"
    document = response.json()
    assert document == {
        "schemaVersion": 1,
        "meta": {"name": "Test Gateway"},
        "chat": {
            "providers": [
                {
                    "id": "paply",
                    "name": "PaplyAI",
                    "api": "openai-responses",
                    "models": [{"id": "paply-chat", "input": ["text"]}],
                    "baseUrl": "https://gateway.paply.test/v1",
                    "apiKey": "test-key-user-alice",
                }
            ]
        },
        "vision": None,
        "imageGen": None,
    }


def test_invalid_virtual_key_is_rejected(config_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid key"})

    app = create_app(make_settings(config_path), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        response = client.get(
            "/api/models",
            headers={"authorization": "Bearer test-key-expired"},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == (
        "The PaplyAI virtual key is invalid, expired, or not a virtual key"
    )


def test_master_key_is_not_accepted_as_a_client_virtual_key(config_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("http://litellm.test/key/info")
        return httpx.Response(404, json={"error": "Key not found in database"})

    app = create_app(make_settings(config_path), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        response = client.get(
            "/api/models",
            headers={"authorization": "Bearer test-master-key"},
        )

    assert response.status_code == 401


def test_explicit_bootstrap_key_supports_the_current_desktop(config_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key-controlled-pilot"
        return httpx.Response(200, json={"key": "test-key-controlled-pilot", "info": {}})

    settings = make_settings(
        config_path,
        paply_models_bootstrap_key="test-key-controlled-pilot",
    )
    app = create_app(settings, transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        response = client.get("/api/models")

    assert response.status_code == 200
    assert response.json()["chat"]["providers"][0]["apiKey"] == "test-key-controlled-pilot"


def test_proxy_preserves_streaming_body_auth_and_status(config_path: Path) -> None:
    class ServerSentEvents(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"data: first\n\n"
            yield b"data: [DONE]\n\n"

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("http://litellm.test/v1/responses?include=usage")
        assert request.headers["authorization"] == "Bearer test-key-user-alice"
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
                "authorization": "Bearer test-key-user-alice",
                "content-type": "application/json",
                "x-request-id": "stream-request",
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


def test_production_rejects_insecure_public_url_and_bootstrap_key(config_path: Path) -> None:
    with pytest.raises(ValidationError, match="must use HTTPS"):
        make_settings(
            config_path,
            paply_environment="production",
            paply_public_base_url="http://gateway.paply.test",
        )

    with pytest.raises(ValidationError, match="must be empty in production"):
        make_settings(
            config_path,
            paply_environment="production",
            paply_models_bootstrap_key="test-key-shared",
        )


def test_invalid_models_document_fails_at_startup(tmp_path: Path) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text("schemaVersion: 2\nchat: {providers: []}\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="violates the desktop contract"):
        create_app(make_settings(path))


def test_committed_models_template_matches_the_desktop_contract() -> None:
    template = load_models_template(Path("config/paply-models.yaml"))

    assert template.schema_version == 1
    assert template.chat.providers[0].models[0].thinking_levels[0] == "off"
