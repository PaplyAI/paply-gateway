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
    paply_litellm_url: str = "http://127.0.0.1:4000"
    paply_public_base_url: str = "http://127.0.0.1:4387"
    paply_models_config_path: Path = Path("config/paply-models.yaml")
    paply_skills_catalog_path: Path | None = None
    paply_auth_jwt_secret: SecretStr | None = None
    paply_auth_jwt_issuer: str = "paply"
    paply_auth_jwt_audience: str = "paply-gateway"
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
        self.paply_public_base_url = self._validate_origin(
            self.paply_public_base_url, "PAPLY_PUBLIC_BASE_URL"
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

    @staticmethod
    def _required_secret(value: SecretStr | None, name: str) -> str:
        if value is None or not value.get_secret_value().strip():
            raise RuntimeError(f"{name} is required for the Paply admin application")
        return value.get_secret_value().strip()
