from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: SecretStr
    object_storage_root: Path
    max_upload_bytes: int = Field(default=25 * 1024 * 1024, gt=0)
    log_level: str = "INFO"
    create_schema: bool = False
    environment: Literal["production", "development", "test"] = "production"
    auth_mode: Literal["oidc", "dev"] = "oidc"
    dev_auth_enabled: bool = False
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    oidc_jwks_json: SecretStr | None = None
    oidc_allowed_algorithms: tuple[str, ...] = ("RS256",)
    oidc_principal_type_claim: str = "principal_type"
    provisioning_principals: frozenset[str] = frozenset()
    postgres_encryption_at_rest_confirmed: bool = False
    object_storage_encryption_at_rest_confirmed: bool = False

    @model_validator(mode="after")
    def validate_production_database_boundary(self) -> Settings:
        if self.create_schema:
            raise ValueError("CREATE_SCHEMA is forbidden; apply schema changes with Alembic")
        try:
            url = make_url(self.database_url.get_secret_value())
        except Exception as exc:
            raise ValueError("DATABASE_URL is not a valid SQLAlchemy URL") from exc
        if url.get_backend_name() != "postgresql":
            raise ValueError("DATABASE_URL must use PostgreSQL")
        if self.environment == "production" and (
            self.auth_mode == "dev" or self.dev_auth_enabled
        ):
            raise ValueError("Development authentication is forbidden in production")
        if self.auth_mode == "dev":
            if not self.dev_auth_enabled:
                raise ValueError("Development authentication requires DEV_AUTH_ENABLED=true")
        else:
            if self.dev_auth_enabled:
                raise ValueError("DEV_AUTH_ENABLED requires AUTH_MODE=dev")
            if not self.oidc_issuer or not self.oidc_audience:
                raise ValueError("OIDC_ISSUER and OIDC_AUDIENCE are required")
            if (self.oidc_jwks_url is None) == (self.oidc_jwks_json is None):
                raise ValueError("Configure exactly one of OIDC_JWKS_URL or OIDC_JWKS_JSON")
            issuer_url = urlparse(self.oidc_issuer)
            if self.environment == "production" and issuer_url.scheme != "https":
                raise ValueError("Production OIDC_ISSUER must use HTTPS")
            if self.oidc_jwks_url:
                jwks_url = urlparse(self.oidc_jwks_url)
                if self.environment == "production" and jwks_url.scheme != "https":
                    raise ValueError("Production OIDC_JWKS_URL must use HTTPS")
            safe_algorithms = {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"}
            if not self.oidc_allowed_algorithms or not set(
                self.oidc_allowed_algorithms
            ).issubset(safe_algorithms):
                raise ValueError("OIDC_ALLOWED_ALGORITHMS contains an unsafe algorithm")
            if not self.oidc_principal_type_claim.isidentifier():
                raise ValueError("OIDC_PRINCIPAL_TYPE_CLAIM is invalid")
        for principal in self.provisioning_principals:
            issuer, separator, subject = principal.partition("|")
            if not separator or not issuer or not subject or "\n" in principal:
                raise ValueError("PROVISIONING_PRINCIPALS contains an invalid identity")
        if self.environment == "production" and not (
            self.postgres_encryption_at_rest_confirmed
            and self.object_storage_encryption_at_rest_confirmed
        ):
            raise ValueError(
                "Production requires deployment-layer encryption at rest for PostgreSQL "
                "and object storage"
            )
        return self
