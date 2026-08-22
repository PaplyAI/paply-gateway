from __future__ import annotations

import asyncio
import gzip
import hashlib
import io
import json
import re
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from paplyai_gateway.settings import Settings
from paplyai_gateway.skill_storage import SkillObjectStore
from paplyai_gateway.skills import (
    MAX_SKILL_ARTIFACT_BYTES,
    SkillCatalog,
    load_skill_catalog,
    load_skill_catalog_bytes,
)

MAX_SOURCE_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_SOURCE_FILES = 10_000
MAX_CONTROL_DOCUMENT_BYTES = 2 * 1024 * 1024
REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class ReleaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SkillSourceConfig(ReleaseModel):
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    ref: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
    catalog_path: str = Field(alias="catalogPath")

    @field_validator("catalog_path")
    @classmethod
    def validate_catalog_path(cls, value: str) -> str:
        path = Path(value)
        if not value or path.is_absolute() or ".." in path.parts:
            raise ValueError("catalogPath must be repository-relative")
        return value


class SkillReleasePointer(ReleaseModel):
    schema_version: Literal[1] = Field(default=1, alias="schemaVersion")
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    catalog_object_key: str = Field(alias="catalogObjectKey")
    catalog_sha256: str = Field(alias="catalogSha256", pattern=r"^[0-9a-f]{64}$")
    published_at: str = Field(alias="publishedAt")


class SkillReleaseRecord(ReleaseModel):
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    published_at: str = Field(alias="publishedAt")
    skill_count: int = Field(alias="skillCount", ge=0)


class SkillReleaseIndex(ReleaseModel):
    schema_version: Literal[1] = Field(default=1, alias="schemaVersion")
    current_revision: str = Field(alias="currentRevision", pattern=r"^[0-9a-f]{40}$")
    releases: list[SkillReleaseRecord]


def _json_bytes(value: BaseModel | dict[str, Any]) -> bytes:
    payload = value.model_dump(by_alias=True) if isinstance(value, BaseModel) else value
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{serialized}\n".encode()


class OssSkillReleaseRepository:
    def __init__(self, settings: Settings, store: SkillObjectStore) -> None:
        self.settings = settings
        self.store = store
        self.prefix = settings.paply_skills_oss_prefix

    def key(self, suffix: str) -> str:
        return f"{self.prefix}/{suffix.lstrip('/')}"

    def default_source(self) -> SkillSourceConfig:
        return SkillSourceConfig(
            repository=self.settings.paply_skills_github_repository,
            ref=self.settings.paply_skills_github_ref,
            catalogPath=self.settings.paply_skills_github_catalog_path,
        )

    def source(self) -> SkillSourceConfig:
        value = self.store.get_optional_bytes(
            self.key("control/source.json"), maximum_bytes=64 * 1024
        )
        if value is None:
            return self.default_source()
        return SkillSourceConfig.model_validate_json(value)

    def save_source(self, source: SkillSourceConfig) -> None:
        self.store.put_bytes(
            self.key("control/source.json"),
            _json_bytes(source),
            content_type="application/json",
        )

    def pointer(self) -> SkillReleasePointer | None:
        value = self.store.get_optional_bytes(
            self.key("control/current.json"), maximum_bytes=64 * 1024
        )
        return None if value is None else SkillReleasePointer.model_validate_json(value)

    def index(self) -> SkillReleaseIndex | None:
        value = self.store.get_optional_bytes(
            self.key("control/releases.json"), maximum_bytes=MAX_CONTROL_DOCUMENT_BYTES
        )
        return None if value is None else SkillReleaseIndex.model_validate_json(value)

    def catalog_for_pointer(self, pointer: SkillReleasePointer) -> SkillCatalog:
        expected_key = self.key(f"releases/{pointer.revision}/catalog.json")
        if pointer.catalog_object_key != expected_key:
            raise RuntimeError("published skill catalog key does not match its revision")
        value = self.store.get_bytes(
            pointer.catalog_object_key, maximum_bytes=MAX_CONTROL_DOCUMENT_BYTES
        )
        if hashlib.sha256(value).hexdigest() != pointer.catalog_sha256:
            raise RuntimeError("published skill catalog checksum mismatch")
        catalog = load_skill_catalog_bytes(value)
        self._validate_release_catalog(catalog, pointer.revision)
        return catalog

    def _validate_release_catalog(self, catalog: SkillCatalog, revision: str) -> None:
        artifact_prefix = self.key(f"releases/{revision}/artifacts/")
        for skill in catalog.skills:
            if skill.status != "available":
                continue
            if not skill.artifact_object_key or not skill.artifact_object_key.startswith(
                artifact_prefix
            ):
                raise RuntimeError(
                    f"published skill artifact key does not match release: {skill.id}"
                )
            if not skill.sha256:
                raise RuntimeError(f"published skill checksum is missing: {skill.id}")

    def current_catalog(self) -> tuple[SkillReleasePointer, SkillCatalog]:
        pointer = self.pointer()
        if pointer is None:
            raise RuntimeError("no OSS skill release has been published")
        return pointer, self.catalog_for_pointer(pointer)

    def revision_catalog(self, revision: str) -> tuple[SkillReleasePointer, SkillCatalog]:
        if not REVISION_PATTERN.fullmatch(revision):
            raise ValueError("invalid skill release revision")
        catalog_key = self.key(f"releases/{revision}/catalog.json")
        value = self.store.get_bytes(catalog_key, maximum_bytes=MAX_CONTROL_DOCUMENT_BYTES)
        pointer = SkillReleasePointer(
            revision=revision,
            catalogObjectKey=catalog_key,
            catalogSha256=hashlib.sha256(value).hexdigest(),
            publishedAt="",
        )
        catalog = load_skill_catalog_bytes(value)
        self._validate_release_catalog(catalog, revision)
        return pointer, catalog

    def publish_pointer(self, pointer: SkillReleasePointer, *, skill_count: int) -> None:
        index = self.index()
        records = [] if index is None else list(index.releases)
        records = [record for record in records if record.revision != pointer.revision]
        records.insert(
            0,
            SkillReleaseRecord(
                revision=pointer.revision,
                publishedAt=pointer.published_at,
                skillCount=skill_count,
            ),
        )
        release_index = SkillReleaseIndex(
            currentRevision=pointer.revision,
            releases=records[:20],
        )
        self.store.put_bytes(
            self.key("control/releases.json"),
            _json_bytes(release_index),
            content_type="application/json",
        )
        self.store.put_bytes(
            self.key("control/current.json"),
            _json_bytes(pointer),
            content_type="application/json",
        )

    def rollback(self, revision: str) -> SkillReleasePointer:
        index = self.index()
        if index is None or revision not in {record.revision for record in index.releases}:
            raise ValueError("requested skill release is not in retained history")
        old_pointer = self.pointer()
        catalog_key = self.key(f"releases/{revision}/catalog.json")
        catalog = self.store.get_bytes(catalog_key, maximum_bytes=MAX_CONTROL_DOCUMENT_BYTES)
        validated = load_skill_catalog_bytes(catalog)
        pointer = SkillReleasePointer(
            revision=revision,
            catalogObjectKey=catalog_key,
            catalogSha256=hashlib.sha256(catalog).hexdigest(),
            publishedAt=datetime.now(UTC).isoformat(),
        )
        try:
            self.publish_pointer(pointer, skill_count=len(validated.skills))
        except Exception:
            if old_pointer is not None:
                self.store.put_bytes(
                    self.key("control/current.json"),
                    _json_bytes(old_pointer),
                    content_type="application/json",
                )
            raise
        return pointer


def _safe_extract_github_archive(value: bytes, target: Path) -> Path:
    total_size = 0
    root_name: str | None = None
    with tarfile.open(fileobj=io.BytesIO(value), mode="r:gz") as archive:
        members = archive.getmembers()
        if len(members) > MAX_SOURCE_FILES:
            raise ValueError("GitHub skill source contains too many files")
        for member in members:
            parts = Path(member.name).parts
            if not parts or member.name.startswith("/") or ".." in parts:
                raise ValueError("GitHub skill source contains an unsafe path")
            root_name = root_name or parts[0]
            if parts[0] != root_name:
                raise ValueError("GitHub skill source must have one archive root")
            relative_parts = parts[1:]
            if not relative_parts:
                continue
            destination = target.joinpath(*relative_parts)
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise ValueError("GitHub skill source may contain only files and directories")
            total_size += member.size
            if total_size > MAX_SOURCE_ARCHIVE_BYTES:
                raise ValueError("GitHub skill source expands beyond the allowed size")
            source = archive.extractfile(member)
            if source is None:
                raise ValueError("GitHub skill source file could not be read")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as output:
                while chunk := source.read(256 * 1024):
                    output.write(chunk)
    return target


def _validate_skill_contract(skill_id: str, version: str, directory: Path) -> None:
    contract_path = directory / "paplyai-skill.json"
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"skill runtime contract is missing or invalid: {skill_id}") from error
    if contract.get("schemaVersion") != 1 or contract.get("id") != skill_id:
        raise ValueError(f"skill runtime contract id mismatch: {skill_id}")
    if contract.get("version") != version:
        raise ValueError(f"skill runtime contract version mismatch: {skill_id}")


def _deterministic_archive(directory: Path) -> bytes:
    output = io.BytesIO()
    with (
        gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive,
    ):
        for path in sorted(directory.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise ValueError(f"skill artifact contains an unsupported entry: {path.name}")
            relative = path.relative_to(directory).as_posix()
            info = tarfile.TarInfo(relative)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            if path.is_dir():
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                archive.addfile(info)
            else:
                data = path.read_bytes()
                info.size = len(data)
                info.mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
                archive.addfile(info, io.BytesIO(data))
    value = output.getvalue()
    if len(value) > MAX_SKILL_ARTIFACT_BYTES:
        raise ValueError("generated skill artifact exceeds the 50 MB client limit")
    return value


async def github_latest_revision(
    client: httpx.AsyncClient,
    source: SkillSourceConfig,
    *,
    token: str | None = None,
) -> str:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "PaplyAI-Gateway",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = await client.get(
        f"https://api.github.com/repos/{source.repository}/commits/{source.ref}",
        headers=headers,
    )
    response.raise_for_status()
    revision = str(response.json().get("sha", ""))
    if not REVISION_PATTERN.fullmatch(revision):
        raise RuntimeError("GitHub returned an invalid skill source revision")
    return revision


async def _put_verified_object(
    repository: OssSkillReleaseRepository,
    key: str,
    value: bytes,
    *,
    content_type: str,
) -> None:
    await asyncio.to_thread(
        repository.store.put_bytes,
        key,
        value,
        content_type=content_type,
    )
    downloaded = await asyncio.to_thread(
        repository.store.get_bytes, key, maximum_bytes=len(value)
    )
    if hashlib.sha256(downloaded).digest() != hashlib.sha256(value).digest():
        raise RuntimeError(f"published OSS object checksum verification failed: {key}")


async def _read_bounded_response(response: httpx.Response) -> bytes:
    declared_length = response.headers.get("content-length")
    if declared_length and int(declared_length) > MAX_SOURCE_ARCHIVE_BYTES:
        raise ValueError("GitHub skill source archive exceeds the allowed size")
    value = bytearray()
    async for chunk in response.aiter_bytes():
        value.extend(chunk)
        if len(value) > MAX_SOURCE_ARCHIVE_BYTES:
            raise ValueError("GitHub skill source archive exceeds the allowed size")
    return bytes(value)


async def publish_github_skills(
    client: httpx.AsyncClient,
    repository: OssSkillReleaseRepository,
    *,
    revision: str | None = None,
) -> SkillReleasePointer:
    source = await asyncio.to_thread(repository.source)
    token = repository.settings.skills_github_token
    resolved_revision = revision or await github_latest_revision(
        client, source, token=token
    )
    if not REVISION_PATTERN.fullmatch(resolved_revision):
        raise ValueError("invalid GitHub revision")
    archive_headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "PaplyAI-Gateway",
    }
    if token:
        archive_headers["Authorization"] = f"Bearer {token}"
    archive_url = (
        f"https://api.github.com/repos/{source.repository}/tarball/{resolved_revision}"
    )
    location: httpx.URL | None = None
    async with client.stream("GET", archive_url, headers=archive_headers) as archive_response:
        if archive_response.status_code in {301, 302, 303, 307, 308}:
            location = httpx.URL(archive_response.headers.get("location", ""))
            if location.scheme != "https" or location.host != "codeload.github.com":
                raise RuntimeError("GitHub returned an unsafe archive redirect")
            archive = b""
        else:
            archive_response.raise_for_status()
            archive = await _read_bounded_response(archive_response)
    if location is not None:
        async with client.stream("GET", location, headers=archive_headers) as response:
            response.raise_for_status()
            archive = await _read_bounded_response(response)

    with TemporaryDirectory(prefix="paplyai-skills-publish-") as temporary:
        root = _safe_extract_github_archive(archive, Path(temporary))
        catalog_path = root / source.catalog_path
        catalog = load_skill_catalog(catalog_path)
        published_skills: list[dict[str, Any]] = []
        release_root = repository.key(f"releases/{resolved_revision}")
        for skill in catalog.skills:
            item = skill.model_dump(by_alias=True, exclude_none=True)
            item.pop("downloadUrl", None)
            artifact_path = item.pop("artifactPath", None)
            item.pop("artifactObjectKey", None)
            if skill.status == "available":
                if not artifact_path:
                    raise ValueError(f"available source skill has no artifactPath: {skill.id}")
                directory = catalog.resolve_artifact(skill)
                _validate_skill_contract(skill.id, skill.version, directory)
                artifact = _deterministic_archive(directory)
                sha256 = hashlib.sha256(artifact).hexdigest()
                object_key = f"{release_root}/artifacts/{skill.id}-{skill.version}-{sha256}.tar.gz"
                await _put_verified_object(
                    repository,
                    object_key,
                    artifact,
                    content_type="application/gzip",
                )
                item["artifactObjectKey"] = object_key
                item["sha256"] = sha256
            published_skills.append(item)

        published_document = {
            "schemaVersion": 1,
            "retiredSkillIds": catalog.retired_skill_ids,
            "skills": published_skills,
        }
        catalog_bytes = _json_bytes(published_document)
        validated = load_skill_catalog_bytes(catalog_bytes)
        catalog_key = f"{release_root}/catalog.json"
        await _put_verified_object(
            repository,
            catalog_key,
            catalog_bytes,
            content_type="application/json",
        )
        pointer = SkillReleasePointer(
            revision=resolved_revision,
            catalogObjectKey=catalog_key,
            catalogSha256=hashlib.sha256(catalog_bytes).hexdigest(),
            publishedAt=datetime.now(UTC).isoformat(),
        )
        await asyncio.to_thread(
            repository.publish_pointer, pointer, skill_count=len(validated.skills)
        )
        return pointer
