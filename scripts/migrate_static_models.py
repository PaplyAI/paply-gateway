#!/usr/bin/env python3
"""Migrate Paply's legacy environment-backed deployments into LiteLLM's DB.

The command is intentionally a one-time operator tool. It defaults to a
read-only plan and requires ``--apply`` before it calls ``/model/new``. It
never prints API keys, authorization headers, or request payloads.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4


@dataclass(frozen=True)
class LegacyDeployment:
    model_name: str
    upstream_model: str
    api_base: str
    api_key: str
    mode: str


class MigrationError(RuntimeError):
    pass


def required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise MigrationError(f"{name} is required")
    return value


def validated_origin(value: str, name: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise MigrationError(f"{name} must be an absolute HTTP(S) URL")
    if parsed.params or parsed.query or parsed.fragment:
        raise MigrationError(f"{name} must not contain params, a query, or a fragment")
    return normalized


def legacy_deployments_from_environment() -> list[LegacyDeployment]:
    shared_key = os.environ.get("OPENAI_API_KEY", "").strip()
    definitions = (
        ("paply-chat", "CHAT", "chat"),
        ("paply-vision", "VISION", "chat"),
        ("paply-image", "IMAGE", "image_generation"),
    )
    deployments: list[LegacyDeployment] = []
    for model_name, capability, mode in definitions:
        key_name = f"PAPLY_{capability}_API_KEY"
        api_key = os.environ.get(key_name, "").strip() or shared_key
        if not api_key:
            raise MigrationError(f"{key_name} or OPENAI_API_KEY is required")
        base_name = f"PAPLY_{capability}_API_BASE"
        deployments.append(
            LegacyDeployment(
                model_name=model_name,
                upstream_model=required_environment(
                    f"PAPLY_{capability}_UPSTREAM_MODEL"
                ),
                api_base=validated_origin(required_environment(base_name), base_name),
                api_key=api_key,
                mode=mode,
            )
        )
    return deployments


class LiteLLMManagementClient:
    def __init__(self, base_url: str, master_key: str, timeout_seconds: float = 20.0):
        self.base_url = validated_origin(base_url, "LiteLLM URL")
        self.master_key = master_key
        self.timeout_seconds = timeout_seconds

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers={
                "authorization": f"Bearer {self.master_key}",
                "content-type": "application/json",
            },
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                response_body = response.read()
        except HTTPError as error:
            raise MigrationError(
                f"LiteLLM {path} returned HTTP {error.code}"
            ) from error
        except (URLError, TimeoutError) as error:
            raise MigrationError(f"LiteLLM {path} is unavailable") from error
        try:
            return json.loads(response_body) if response_body else None
        except json.JSONDecodeError as error:
            raise MigrationError(f"LiteLLM {path} returned invalid JSON") from error

    def deployments(self) -> list[dict[str, Any]]:
        document = self._request("GET", "/model/info")
        if not isinstance(document, dict) or not isinstance(document.get("data"), list):
            raise MigrationError("LiteLLM /model/info returned an invalid document")
        return document["data"]

    def create(self, deployment: LegacyDeployment) -> None:
        self._request(
            "POST",
            "/model/new",
            {
                "model_name": deployment.model_name,
                "litellm_params": {
                    "model": deployment.upstream_model,
                    "api_base": deployment.api_base,
                    "api_key": deployment.api_key,
                },
                "model_info": {
                    "id": str(uuid4()),
                    "mode": deployment.mode,
                    "migration_source": "paply-static-environment-v1",
                },
            },
        )


def is_database_match(item: dict[str, Any], desired: LegacyDeployment) -> bool:
    params = item.get("litellm_params") or {}
    info = item.get("model_info") or {}
    api_base = str(params.get("api_base") or "").rstrip("/")
    return bool(
        info.get("db_model") is True
        and item.get("model_name") == desired.model_name
        and params.get("model") == desired.upstream_model
        and api_base == desired.api_base
    )


def migration_plan(
    current: list[dict[str, Any]], desired: list[LegacyDeployment]
) -> list[LegacyDeployment]:
    return [
        deployment
        for deployment in desired
        if not any(is_database_match(item, deployment) for item in current)
    ]


def run(*, apply: bool, base_url: str) -> int:
    master_key = required_environment("LITELLM_MASTER_KEY")
    desired = legacy_deployments_from_environment()
    client = LiteLLMManagementClient(base_url, master_key)
    pending = migration_plan(client.deployments(), desired)
    if not pending:
        print("All legacy deployments already exist in LiteLLM PostgreSQL.")
        return 0
    for deployment in pending:
        print(
            f"PLAN create database deployment {deployment.model_name} "
            f"({deployment.upstream_model})"
        )
    if not apply:
        print("No changes made. Re-run with --apply after reviewing the plan.")
        return 0
    for deployment in pending:
        client.create(deployment)
        print(f"CREATED database deployment {deployment.model_name}")
    remaining = migration_plan(client.deployments(), desired)
    if remaining:
        names = ", ".join(item.model_name for item in remaining)
        raise MigrationError(f"database verification failed for: {names}")
    print("Migration verified. Config-owned deployments can now be removed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="create missing DB deployments")
    parser.add_argument(
        "--litellm-url",
        default=os.environ.get("PAPLY_LITELLM_MIGRATION_URL", "http://127.0.0.1:4000"),
        help="operator-only LiteLLM origin",
    )
    args = parser.parse_args()
    try:
        return run(apply=args.apply, base_url=args.litellm_url)
    except MigrationError as error:
        print(f"migration failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
