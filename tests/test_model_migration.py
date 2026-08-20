import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "migrate_static_models.py"
SPEC = spec_from_file_location("migrate_static_models", SCRIPT_PATH)
assert SPEC and SPEC.loader
migration = module_from_spec(SPEC)
sys.modules[SPEC.name] = migration
SPEC.loader.exec_module(migration)


def set_legacy_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "shared-secret")
    for capability, upstream in (
        ("CHAT", "openai/chat-model"),
        ("VISION", "openai/vision-model"),
        ("IMAGE", "openai/image-model"),
    ):
        monkeypatch.setenv(f"PAPLY_{capability}_UPSTREAM_MODEL", upstream)
        monkeypatch.setenv(
            f"PAPLY_{capability}_API_BASE",
            f"https://{capability.lower()}.example.test/v1/",
        )


def test_reads_three_legacy_deployments_without_exposing_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_legacy_environment(monkeypatch)

    deployments = migration.legacy_deployments_from_environment()

    assert [item.model_name for item in deployments] == [
        "paply-chat",
        "paply-vision",
        "paply-image",
    ]
    assert deployments[0].api_base == "https://chat.example.test/v1"
    assert deployments[0].api_key == "shared-secret"
    assert deployments[2].mode == "image_generation"


def test_requires_each_upstream_model(monkeypatch: pytest.MonkeyPatch) -> None:
    set_legacy_environment(monkeypatch)
    monkeypatch.delenv("PAPLY_VISION_UPSTREAM_MODEL")

    with pytest.raises(migration.MigrationError, match="PAPLY_VISION_UPSTREAM_MODEL"):
        migration.legacy_deployments_from_environment()


def test_plan_ignores_static_match_but_skips_database_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_legacy_environment(monkeypatch)
    desired = migration.legacy_deployments_from_environment()
    chat = desired[0]
    matching_params = {"model": chat.upstream_model, "api_base": chat.api_base}
    current = [
        {
            "model_name": chat.model_name,
            "litellm_params": matching_params,
            "model_info": {"db_model": False},
        },
        {
            "model_name": chat.model_name,
            "litellm_params": matching_params,
            "model_info": {"db_model": True},
        },
    ]

    pending = migration.migration_plan(current, desired)

    assert [item.model_name for item in pending] == ["paply-vision", "paply-image"]
