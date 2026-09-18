from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from DEFENSE_* environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="DEFENSE_",
        extra="ignore",
    )

    environment: Literal["local", "test", "production"] = "local"
    database_url: str = "sqlite+aiosqlite:///./data/defense_grouping.db"
    jwt_secret: str = Field(min_length=32)
    access_token_minutes: int = Field(default=15, ge=1)
    refresh_token_days: int = Field(default=7, ge=1)
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8765, ge=1, le=65535)
    display_timezone: str = "Asia/Shanghai"
    storage_dir: Path = Path("./data/storage")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
