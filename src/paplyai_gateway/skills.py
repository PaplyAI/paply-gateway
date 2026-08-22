import json
import os
import re
import tarfile
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_SKILL_ARTIFACT_BYTES = 50 * 1024 * 1024

BuiltinCapabilityId = Literal[
    "web-access",
    "planning",
    "swarm",
    "document-suite",
    "image-engine",
]
SkillCategory = Literal[
    "research-workflow",
    "document-delivery",
    "visual-expression",
    "writing-expression",
]
SkillKind = Literal["workflow", "skill"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class LocalizedDisplayCopy(StrictModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)


class SkillCatalogEntry(StrictModel):
    id: str = Field(pattern=r"^paplyai-[a-z0-9][a-z0-9-]{1,55}$")
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    translations: dict[Literal["zh", "en"], LocalizedDisplayCopy] | None = None
    version: str = "1.0.0"
    kind: SkillKind
    category: SkillCategory
    order: int = Field(ge=0)
    required_capabilities: list[BuiltinCapabilityId] = Field(alias="requiredCapabilities")
    composes: list[str]
    download_url: str | None = Field(default=None, alias="downloadUrl")
    artifact_path: str | None = Field(default=None, alias="artifactPath")
    status: Literal["available", "adapting"]
    license: str | None = None
    upstream: str | None = None
    source_revision: str | None = Field(default=None, alias="sourceRevision")
    runtime: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    replaces: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_available_artifact(self) -> "SkillCatalogEntry":
        if self.status == "available" and not (self.download_url or self.artifact_path):
            raise ValueError("available skills require downloadUrl or artifactPath")
        if any(
            not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", legacy_id)
            for legacy_id in self.replaces
        ):
            raise ValueError("replaced skill ids must be valid legacy ids")
        if len(self.required_capabilities) != len(set(self.required_capabilities)):
            raise ValueError("required capability ids must be unique")
        if len(self.composes) != len(set(self.composes)) or any(
            not re.fullmatch(r"paplyai-[a-z0-9][a-z0-9-]{1,55}", skill_id)
            for skill_id in self.composes
        ):
            raise ValueError("composed skill ids must be unique canonical ids")
        if self.translations is not None and set(self.translations) != {"zh", "en"}:
            raise ValueError("skill translations must contain exactly zh and en")
        return self


class SkillCatalog(StrictModel):
    schema_version: Literal[1] = Field(alias="schemaVersion")
    retired_skill_ids: list[str] = Field(default_factory=list, alias="retiredSkillIds")
    skills: list[SkillCatalogEntry]
    root: Path = Field(exclude=True)

    @model_validator(mode="after")
    def require_unique_ids(self) -> "SkillCatalog":
        ids = [skill.id for skill in self.skills]
        if len(ids) != len(set(ids)):
            raise ValueError("skill ids must be unique")
        replaced_ids = [legacy_id for skill in self.skills for legacy_id in skill.replaces]
        if len(replaced_ids) != len(set(replaced_ids)):
            raise ValueError("replaced skill ids must be unique")
        if set(ids).intersection(replaced_ids):
            raise ValueError("a current skill id cannot also be a replaced skill id")
        if len(self.retired_skill_ids) != len(set(self.retired_skill_ids)) or any(
            not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", skill_id)
            for skill_id in self.retired_skill_ids
        ):
            raise ValueError("retired skill ids must be unique valid managed ids")
        if set(self.retired_skill_ids).intersection(ids) or set(
            self.retired_skill_ids
        ).intersection(replaced_ids):
            raise ValueError("retired skill ids cannot overlap current or replaced ids")
        orders = [skill.order for skill in self.skills]
        if len(orders) != len(set(orders)):
            raise ValueError("skill display order values must be unique")
        known_ids = set(ids)
        composition = {skill.id: skill.composes for skill in self.skills}
        for skill in self.skills:
            if skill.id in skill.composes or not set(skill.composes).issubset(known_ids):
                raise ValueError(f"skill composition references an unknown or self id: {skill.id}")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(skill_id: str) -> None:
            if skill_id in visiting:
                raise ValueError(f"skill composition contains a cycle: {skill_id}")
            if skill_id in visited:
                return
            visiting.add(skill_id)
            for composed_id in composition[skill_id]:
                visit(composed_id)
            visiting.remove(skill_id)
            visited.add(skill_id)

        for skill_id in ids:
            visit(skill_id)
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
        return {
            "schemaVersion": 1,
            "retiredSkillIds": self.retired_skill_ids,
            "skills": skills,
        }

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
    descriptor, archive_name = tempfile.mkstemp(prefix=f"paplyai-skill-{skill.id}-", suffix=".tgz")
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
