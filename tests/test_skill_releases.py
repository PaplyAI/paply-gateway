import asyncio
import io
import json
import tarfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from paplyai_gateway.admin import create_admin_app
from paplyai_gateway.app import create_app
from paplyai_gateway.auth import encode_access_token
from paplyai_gateway.settings import Settings
from paplyai_gateway.skill_releases import (
    OssSkillReleaseRepository,
    publish_github_skills,
)
from paplyai_gateway.skill_storage import MemorySkillStore

REVISION = "a" * 40
MODELS = """
schemaVersion: 2
chat:
  providers:
    - id: paply
      name: Paply
      api: openai-responses
      models:
        - id: paply-chat
          input: [text]
vision: null
imageGen: null
"""


def settings(tmp_path: Path) -> Settings:
    models = tmp_path / "models.yaml"
    models.write_text(MODELS, encoding="utf-8")
    return Settings(
        paply_environment="development",
        paply_litellm_url="http://litellm.test",
        paplyai_gateway_internal_url="http://gateway.test",
        paply_public_base_url="https://gateway.paply.test",
        paply_models_config_path=models,
        paply_accounts_db_path=tmp_path / "accounts.sqlite3",
        paply_auth_jwt_secret="test-paply-jwt-secret",
        paply_auth_jwt_issuer="paply-test",
        paply_auth_jwt_audience="paplyai-gateway-test",
        paply_litellm_service_token="test-service-token",
        litellm_master_key="test-master-key",
        paply_admin_username="paply_test",
        paply_admin_password="test-admin-password",
        paply_admin_session_secret="test-session-secret-with-sufficient-length",
        paply_skills_storage="oss",
        paply_skills_oss_endpoint="https://oss-cn-shenzhen-internal.aliyuncs.com",
        paply_skills_oss_region="cn-shenzhen",
        paply_skills_oss_bucket="paplyai-skills",
        _env_file=None,
    )


def source_archive(*, contract_version: str = "1.2.3") -> bytes:
    catalog = {
        "schemaVersion": 1,
        "retiredSkillIds": [],
        "skills": [
            {
                "id": "paplyai-test-skill",
                "name": "测试技能",
                "description": "测试技能发布",
                "version": contract_version,
                "kind": "skill",
                "category": "document-delivery",
                "order": 10,
                "requiredCapabilities": ["document-suite"],
                "composes": [],
                "artifactPath": "skills/paplyai-test-skill",
                "status": "available",
            }
        ],
    }
    files = {
        "repository/catalog.json": json.dumps(catalog).encode(),
        "repository/skills/paplyai-test-skill/SKILL.md": b"---\nname: test\n---\n",
        "repository/skills/paplyai-test-skill/paplyai-skill.json": json.dumps(
            {
                "schemaVersion": 1,
                "id": "paplyai-test-skill",
                "version": "1.2.3",
                "execution": {
                    "network": "none",
                    "workspace": "read-only",
                    "managedSkillWrite": False,
                },
                "runtime": {"kind": "static"},
                "outputs": {"artifacts": "optional", "formats": []},
            }
        ).encode(),
    }
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, value in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(value)
            archive.addfile(info, io.BytesIO(value))
    return output.getvalue()


def github_transport(archive: bytes) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com" and "/commits/" in request.url.path:
            return httpx.Response(200, json={"sha": REVISION})
        if request.url.host == "api.github.com" and "/tarball/" in request.url.path:
            return httpx.Response(
                302,
                headers={
                    "location": f"https://codeload.github.com/PaplyAI/paplyai-skills/legacy.tar.gz/{REVISION}"
                },
            )
        if request.url.host == "codeload.github.com":
            return httpx.Response(200, content=archive)
        raise AssertionError(f"unexpected request: {request.url}")

    return httpx.MockTransport(handler)


def bearer() -> dict[str, str]:
    token = encode_access_token(
        user_id="user-test",
        secret="test-paply-jwt-secret",
        issuer="paply-test",
        audience="paplyai-gateway-test",
        issued_at=1_700_000_000,
        expires_at=4_000_000_000,
    )
    return {"authorization": f"Bearer {token}"}


def test_publish_creates_immutable_artifact_and_gateway_streams_it(tmp_path: Path) -> None:
    runtime_settings = settings(tmp_path)
    store = MemorySkillStore()
    repository = OssSkillReleaseRepository(runtime_settings, store)
    archive = source_archive()

    async def publish() -> None:
        async with httpx.AsyncClient(transport=github_transport(archive)) as client:
            await publish_github_skills(client, repository)

    asyncio.run(publish())
    pointer, catalog = repository.current_catalog()
    skill = catalog.skill("paplyai-test-skill")
    assert pointer.revision == REVISION
    assert skill is not None and skill.artifact_object_key
    assert skill.sha256

    app = create_app(runtime_settings, skill_store=store)
    with TestClient(app) as client:
        catalog_response = client.get("/api/skills", headers=bearer())
        assert catalog_response.status_code == 200
        download_url = catalog_response.json()["skills"][0]["downloadUrl"]
        assert f"/revisions/{REVISION}/artifact" in download_url
        artifact_response = client.get(download_url, headers=bearer())

    assert artifact_response.status_code == 200
    assert artifact_response.content == store.objects[skill.artifact_object_key]
    assert artifact_response.headers["cache-control"] == "private, no-store"
    with tarfile.open(fileobj=io.BytesIO(artifact_response.content), mode="r:gz") as artifact:
        assert "SKILL.md" in artifact.getnames()
        assert "paplyai-skill.json" in artifact.getnames()


def test_publish_failure_does_not_change_current_pointer(tmp_path: Path) -> None:
    runtime_settings = settings(tmp_path)
    store = MemorySkillStore()
    repository = OssSkillReleaseRepository(runtime_settings, store)
    bad_archive = source_archive(contract_version="9.9.9")

    async def publish() -> None:
        async with httpx.AsyncClient(transport=github_transport(bad_archive)) as client:
            await publish_github_skills(client, repository)

    with pytest.raises(ValueError, match="version mismatch"):
        asyncio.run(publish())
    assert repository.pointer() is None


def test_admin_exposes_and_updates_skill_source_configuration(tmp_path: Path) -> None:
    runtime_settings = settings(tmp_path)
    store = MemorySkillStore()
    app = create_admin_app(
        runtime_settings,
        transport=github_transport(source_archive()),
        skill_store=store,
    )
    with TestClient(app) as client:
        assert client.get("/api/admin/skills").status_code == 401
        login = client.post(
            "/api/admin/session",
            json={"username": "paply_test", "password": "test-admin-password"},
        )
        csrf = login.json()["data"]["csrf_token"]
        status = client.get("/api/admin/skills")
        assert status.status_code == 200
        assert status.json()["data"]["storage"]["bucket"] == "paplyai-skills"
        update = client.patch(
            "/api/admin/skills/source",
            headers={"x-csrf-token": csrf},
            json={
                "repository": "PaplyAI/paplyai-skills",
                "ref": "stable",
                "catalogPath": "catalog.json",
            },
        )
        assert update.status_code == 200

    repository = OssSkillReleaseRepository(runtime_settings, store)
    assert repository.source().ref == "stable"
