from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str
    database_url: str
    openai_api_key: str | None = None
    openai_chat_model: str = "gpt-5-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    allowed_telegram_user_ids: Annotated[frozenset[int], NoDecode] = Field(
        default_factory=frozenset
    )
    storage_dir: Path = Path("./data/files")
    max_download_mb: int = Field(default=30, ge=1, le=500)
    search_result_limit: int = Field(default=5, ge=1, le=20)
    log_level: str = "INFO"

    @field_validator("allowed_telegram_user_ids", mode="before")
    @classmethod
    def parse_user_ids(cls, value: object) -> frozenset[int]:
        if value in (None, "", []):
            return frozenset()
        if isinstance(value, str):
            return frozenset(int(item.strip()) for item in value.split(",") if item.strip())
        return frozenset(int(item) for item in value)  # type: ignore[arg-type]

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value.startswith(("postgresql://", "postgres://")):
            raise ValueError("DATABASE_URL phai la PostgreSQL connection string")
        return value

    @property
    def max_download_bytes(self) -> int:
        return self.max_download_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
