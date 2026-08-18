from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: SecretStr
    object_storage_root: Path
    max_upload_bytes: int = Field(default=25 * 1024 * 1024, gt=0)
    log_level: str = "INFO"
    create_schema: bool = False
