import os
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    # App Settings
    ENV: str = "development"
    PROJECT_NAME: str = "Pivot Server"
    SERVER_PUBLIC_BASE_URL: str = "http://localhost:8003"
    WEB_PUBLIC_BASE_URL: str | None = None
    CHANNEL_RUNTIME_SCAN_INTERVAL_SECONDS: int = 5
    CHANNEL_PROGRESS_MIN_INTERVAL_SECONDS: float = 1.0
    REACT_CURRENT_PLAN_HISTORY_LIMIT: int = 3
    WORK_WECHAT_WS_URL: str = "wss://openws.work.weixin.qq.com"
    WORK_WECHAT_WS_HEARTBEAT_SECONDS: int = 30
    WORK_WECHAT_WS_REQUEST_TIMEOUT_SECONDS: int = 10

    # Database
    DATABASE_URL: str = "sqlite:///./app.db"

    # Sandbox manager
    SANDBOX_MANAGER_URL: str = "http://sandbox-manager:8051"
    SANDBOX_MANAGER_TOKEN: str = "dev-sandbox-token"
    SANDBOX_MANAGER_TIMEOUT_SECONDS: int = 30

    # Storage
    STORAGE_PROFILE: str = "local_fs"
    STORAGE_LOCAL_ROOT: str | None = None
    LOCAL_CACHE_ROOT: str | None = None
    STORAGE_SEAWEEDFS_FILER_ENDPOINT: str | None = None
    STORAGE_SEAWEEDFS_S3_ENDPOINT: str | None = None
    STORAGE_SEAWEEDFS_ACCESS_KEY: str | None = None
    STORAGE_SEAWEEDFS_SECRET_KEY: str | None = None
    STORAGE_SEAWEEDFS_BUCKET: str | None = None
    STORAGE_SEAWEEDFS_POSIX_ROOT: str | None = None
    STORAGE_SEAWEEDFS_HOST_POSIX_ROOT: str | None = None

    # File uploads
    MAX_IMAGE_SIZE: int = Field(
        default=2 * 1024 * 1024,
        validation_alias=AliasChoices("MAX_IMAGE_SIZE", "MAX_FILESIZE"),
    )
    MAX_FILE_SIZE: int = 10 * 1024 * 1024
    FILE_EXPIRE_MINUTES: int = 120
    FILE_PRUNE_INTERVAL_MINUTES: int = 5

    @property
    def server_public_base_url(self) -> str:
        """Return the normalized external backend base URL."""
        return self.SERVER_PUBLIC_BASE_URL.rstrip("/")

    @property
    def web_public_base_url(self) -> str:
        """Return the normalized external web base URL.

        Why: channel link pages may be served from the same backend in production
        or from a separate Vite server during development.
        """
        raw_url = self.WEB_PUBLIC_BASE_URL or self.SERVER_PUBLIC_BASE_URL
        return raw_url.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    """Load and cache runtime settings from the selected environment file."""
    env = os.getenv("ENV", "development")

    # server/app/config.py -> server/
    server_dir = Path(__file__).resolve().parent.parent
    env_file = server_dir / f".env.{env}"

    # If specific env file exists, use it
    if env_file.exists():
        return cast(Any, Settings)(_env_file=str(env_file), ENV=env)

    # Fallback to .env in server dir
    base_env = server_dir / ".env"
    if base_env.exists():
        return cast(Any, Settings)(_env_file=str(base_env), ENV=env)

    return Settings(ENV=env)
