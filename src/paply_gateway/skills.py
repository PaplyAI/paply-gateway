import json
import os
import tarfile
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_SKILL_ARTIFACT_BYTES = 50 * 1024 * 1024


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SkillCatalogEntry(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    version: str = "1.0.0"
    category: str = Field(min_length=1)
    download_url: str | None = Field(default=None, alias="downloadUrl")
    artifact_path: str | None = Field(default=None, alias="artifactPath")
    status: Literal["available", "adapting"]
    license: str | None = None
    upstream: str | None = None
    source_revision: str | None = Field(default=None, alias="sourceRevision")
    runtime: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")

    @model_validator(mode="after")
    def require_available_artifact(self) -> "SkillCatalogEntry":
        if self.status == "available" and not (self.download_url or self.artifact_path):
            raise ValueError("available skills require downloadUrl or artifactPath")
        return self


class SkillCatalog(StrictModel):
    schema_version: Literal[1] = Field(alias="schemaVersion")
    skills: list[SkillCatalogEntry]
    root: Path = Field(exclude=True)

    @model_validator(mode="after")
    def require_unique_ids(self) -> "SkillCatalog":
        ids = [skill.id for skill in self.skills]
        if len(ids) != len(set(ids)):
            raise ValueError("skill ids must be unique")
        for skill in self.skills:
            if skill.artifact_path:
                self.resolve_artifact(skill)
        return self

    def resolve_artifact(self, skill: SkillCatalogEntry) -> Path:
        if not skill.artifact_path:
            raise ValueError(f"skill {skill.id} does not have a local artifact")
        root = self.root.resolve()
        artifact = (root / skill.artifact_path).resolve()
        if not artifact.is_relative_to(root):
            raise ValueError(f"skill artifact escapes the catalog root: {skill.id}")
        if not artifact.is_dir() or not (artifact / "SKILL.md").is_file():
            raise ValueError(f"skill artifact is invalid: {skill.id}")
        if any(path.is_symlink() for path in artifact.rglob("*")):
            raise ValueError(f"skill artifact contains symbolic links: {skill.id}")
        return artifact

    def public_document(self, base_url: str) -> dict[str, object]:
        skills: list[dict[str, object]] = []
        for skill in self.skills:
            item = skill.model_dump(
                by_alias=True,
                exclude_none=True,
                exclude={"artifact_path", "download_url"},
            )
            if skill.status == "available" and skill.artifact_path:
                item["downloadUrl"] = (
                    f"{base_url.rstrip('/')}/api/skills/{skill.id}/artifact"
                )
            else:
                item["downloadUrl"] = skill.download_url
            skills.append(item)
        return {"schemaVersion": 1, "skills": skills}

    def skill(self, skill_id: str) -> SkillCatalogEntry | None:
        return next((skill for skill in self.skills if skill.id == skill_id), None)


def load_skill_catalog(path: Path) -> SkillCatalog:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise RuntimeError(f"skills catalog does not exist: {path}") from error
    except (OSError, ValueError) as error:
        raise RuntimeError(f"skills catalog cannot be read: {path}") from error
    try:
        return SkillCatalog.model_validate({**payload, "root": path.parent})
    except (TypeError, ValueError) as error:
        raise RuntimeError(f"skills catalog is invalid: {path}") from error


def create_skill_archive(catalog: SkillCatalog, skill: SkillCatalogEntry) -> Path:
    artifact = catalog.resolve_artifact(skill)
    descriptor, archive_name = tempfile.mkstemp(prefix=f"paply-skill-{skill.id}-", suffix=".tgz")
    os.close(descriptor)
    archive_path = Path(archive_name)
    try:
        with tarfile.open(archive_path, mode="w:gz", compresslevel=6) as archive:
            archive.add(artifact, arcname=".", recursive=True)
        if archive_path.stat().st_size > MAX_SKILL_ARTIFACT_BYTES:
            raise ValueError(f"skill artifact exceeds the 50 MB client limit: {skill.id}")
        return archive_path
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise
