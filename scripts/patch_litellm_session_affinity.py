"""Make LiteLLM session affinity fail closed for stateful Paply chat sessions."""

from __future__ import annotations

from pathlib import Path

UNSAFE_FALLTHROUGH = (
    "                    else:\n"
    "                        verbose_router_logger.debug(\n"
    '                            "DeploymentAffinityCheck: session-id pinned '
    'deployment=%s not found in healthy_deployments",\n'
    "                            session_model_id,\n"
    "                        )\n"
)

FAIL_CLOSED = UNSAFE_FALLTHROUGH + "                        return []\n"


def patch_source(source: str) -> str:
    occurrences = source.count(UNSAFE_FALLTHROUGH)
    if occurrences != 1:
        raise RuntimeError(
            "Unexpected LiteLLM deployment affinity implementation: "
            f"expected one pinned-deployment fallthrough, found {occurrences}"
        )
    return source.replace(UNSAFE_FALLTHROUGH, FAIL_CLOSED, 1)


def main() -> None:
    from litellm.router_utils.pre_call_checks import deployment_affinity_check

    target = Path(deployment_affinity_check.__file__).resolve()
    source = target.read_text(encoding="utf-8")
    target.write_text(patch_source(source), encoding="utf-8")
    print(f"Made LiteLLM session affinity fail closed: {target}")


if __name__ == "__main__":
    main()
