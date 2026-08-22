import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    paply_environment: Literal["development", "staging", "production"] = "development"
    paplyai_gateway_internal_url: str = "http://127.0.0.1:4387"
    paply_litellm_url: str = "http://127.0.0.1:4000"
    paply_litellm_ui_public_url: str | None = None
    paply_public_base_url: str = "http://127.0.0.1:4387"
    paply_models_config_path: Path = Path("config/paply-models.yaml")
    paply_skills_catalog_path: Path | None = None
    paply_skills_storage: Literal["local", "oss"] = "local"
    paply_skills_oss_endpoint: str | None = None
    paply_skills_oss_region: str | None = None
    paply_skills_oss_bucket: str | None = None
    paply_skills_oss_prefix: str = "skills"
    paply_skills_oss_credentials: Literal["ecs_ram_role", "default"] = "ecs_ram_role"
    paply_skills_oss_ecs_role_name: str | None = None
    paply_skills_github_repository: str = "PaplyAI/paplyai-skills"
    paply_skills_github_ref: str = "main"
    paply_skills_github_catalog_path: str = "catalog.json"
    paply_skills_github_token: SecretStr | None = None
    paply_accounts_db_path: Path = Path("data/accounts.sqlite3")
    paply_auth_jwt_secret: SecretStr | None = None
    paply_auth_jwt_issuer: str = "paply"
    paply_auth_jwt_audience: str = "paplyai-gateway"
    paply_auth_access_token_seconds: int = 3600
    paply_auth_refresh_token_seconds: int = 30 * 24 * 3600
    paply_default_user_budget: float = 20.0
    paply_default_user_budget_duration: str = "30d"
    paply_litellm_service_token: SecretStr | None = None
    paply_upstream_timeout_seconds: float = 600.0
    paply_admin_username: str | None = None
    paply_admin_password: SecretStr | None = None
    paply_admin_session_secret: SecretStr | None = None
    litellm_master_key: SecretStr | None = None

    @model_validator(mode="after")
    def validate_runtime_settings(self) -> "Settings":
        self.paply_litellm_url = self._validate_origin(
            self.paply_litellm_url, "PAPLY_LITELLM_URL"
        )
        self.paplyai_gateway_internal_url = self._validate_origin(
            self.paplyai_gateway_internal_url, "PAPLY_GATEWAY_INTERNAL_URL"
        )
        self.paply_public_base_url = self._validate_origin(
            self.paply_public_base_url, "PAPLY_PUBLIC_BASE_URL"
        )
        if self.paply_litellm_ui_public_url is not None:
            self.paply_litellm_ui_public_url = self._validate_origin(
                self.paply_litellm_ui_public_url, "PAPLY_LITELLM_UI_PUBLIC_URL"
            )
        if self.paply_upstream_timeout_seconds <= 0:
            raise ValueError("PAPLY_UPSTREAM_TIMEOUT_SECONDS must be greater than zero")
        if (
            self.paply_environment == "production"
            and urlparse(self.paply_public_base_url).scheme != "https"
        ):
            raise ValueError("PAPLY_PUBLIC_BASE_URL must use HTTPS in production")
        if not self.paply_auth_jwt_issuer.strip():
            raise ValueError("PAPLY_AUTH_JWT_ISSUER must not be empty")
        if not self.paply_auth_jwt_audience.strip():
            raise ValueError("PAPLY_AUTH_JWT_AUDIENCE must not be empty")
        if self.paply_auth_access_token_seconds <= 0:
            raise ValueError("PAPLY_AUTH_ACCESS_TOKEN_SECONDS must be greater than zero")
        if self.paply_auth_refresh_token_seconds <= self.paply_auth_access_token_seconds:
            raise ValueError(
                "PAPLY_AUTH_REFRESH_TOKEN_SECONDS must exceed the access token lifetime"
            )
        if self.paply_default_user_budget <= 0:
            raise ValueError("PAPLY_DEFAULT_USER_BUDGET must be greater than zero")
        if not self.paply_default_user_budget_duration.strip():
            raise ValueError("PAPLY_DEFAULT_USER_BUDGET_DURATION must not be empty")
        if self.paply_skills_storage == "oss":
            missing = [
                name
                for name, value in (
                    ("PAPLY_SKILLS_OSS_ENDPOINT", self.paply_skills_oss_endpoint),
                    ("PAPLY_SKILLS_OSS_REGION", self.paply_skills_oss_region),
                    ("PAPLY_SKILLS_OSS_BUCKET", self.paply_skills_oss_bucket),
                )
                if value is None or not value.strip()
            ]
            if missing:
                raise ValueError(f"OSS skill storage requires: {', '.join(missing)}")
            endpoint = self.paply_skills_oss_endpoint or ""
            parsed_endpoint = urlparse(endpoint)
            if parsed_endpoint.scheme != "https" or not parsed_endpoint.netloc:
                raise ValueError("PAPLY_SKILLS_OSS_ENDPOINT must be an HTTPS endpoint")
            self.paply_skills_oss_endpoint = endpoint.rstrip("/")
        self.paply_skills_oss_prefix = self.paply_skills_oss_prefix.strip("/")
        if not re.fullmatch(
            r"[a-zA-Z0-9][a-zA-Z0-9._/-]{0,127}",
            self.paply_skills_oss_prefix,
        ):
            raise ValueError("PAPLY_SKILLS_OSS_PREFIX is invalid")
        if not re.fullmatch(
            r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.paply_skills_github_repository
        ):
            raise ValueError("PAPLY_SKILLS_GITHUB_REPOSITORY must use owner/repository")
        if not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}",
            self.paply_skills_github_ref,
        ):
            raise ValueError("PAPLY_SKILLS_GITHUB_REF is invalid")
        catalog_path = Path(self.paply_skills_github_catalog_path)
        if catalog_path.is_absolute() or ".." in catalog_path.parts:
            raise ValueError("PAPLY_SKILLS_GITHUB_CATALOG_PATH must be repository-relative")
        return self

    @staticmethod
    def _validate_origin(value: str, name: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"{name} must be an absolute HTTP(S) URL")
        if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
            raise ValueError(f"{name} must be an origin without a path, query, or fragment")
        return normalized

    @property
    def auth_jwt_secret(self) -> str:
        return self._required_secret(self.paply_auth_jwt_secret, "PAPLY_AUTH_JWT_SECRET")

    @property
    def litellm_service_token(self) -> str:
        return self._required_secret(
            self.paply_litellm_service_token,
            "PAPLY_LITELLM_SERVICE_TOKEN",
        )

    @property
    def public_v1_base_url(self) -> str:
        return f"{self.paply_public_base_url}/v1"

    @property
    def admin_password(self) -> str:
        return self._required_secret(self.paply_admin_password, "PAPLY_ADMIN_PASSWORD")

    @property
    def admin_session_secret(self) -> str:
        return self._required_secret(
            self.paply_admin_session_secret,
            "PAPLY_ADMIN_SESSION_SECRET",
        )

    @property
    def master_key(self) -> str:
        return self._required_secret(self.litellm_master_key, "LITELLM_MASTER_KEY")

    @property
    def skills_github_token(self) -> str | None:
        if self.paply_skills_github_token is None:
            return None
        value = self.paply_skills_github_token.get_secret_value().strip()
        return value or None

    @staticmethod
    def _required_secret(value: SecretStr | None, name: str) -> str:
        if value is None or not value.get_secret_value().strip():
            raise RuntimeError(f"{name} is required for the PaplyAI Gateway runtime")
        return value.get_secret_value().strip()
