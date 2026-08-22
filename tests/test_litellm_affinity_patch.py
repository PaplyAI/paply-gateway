import importlib.util
from pathlib import Path
from types import ModuleType


def load_patch_module() -> ModuleType:
    script = Path(__file__).parents[1] / "scripts" / "patch_litellm_session_affinity.py"
    spec = importlib.util.spec_from_file_location("patch_litellm_session_affinity", script)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the LiteLLM affinity patch")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_session_affinity_patch_fails_closed_when_pinned_deployment_is_unhealthy() -> None:
    module = load_patch_module()
    source = f"before\n{module.UNSAFE_FALLTHROUGH}after\n"

    patched = module.patch_source(source)

    assert "                        return []\n" in patched
    assert patched.endswith("after\n")


def test_session_affinity_patch_rejects_an_unknown_upstream_implementation() -> None:
    module = load_patch_module()

    try:
        module.patch_source("upstream changed")
    except RuntimeError as error:
        assert "expected one pinned-deployment fallthrough" in str(error)
    else:
        raise AssertionError("Expected an unknown LiteLLM implementation to fail")
