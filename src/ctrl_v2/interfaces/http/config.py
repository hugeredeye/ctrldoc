from __future__ import annotations

from pathlib import Path

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
        return self
