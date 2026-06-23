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

    # ReactEngine — streaming content emit cadence
    # How often (ms) to coalesce high-frequency streaming-content events
    # (tool_payload_delta / answer_delta / reasoning) before pushing them to
    # the SSE stream.  Without this buffer the extractor emits one event per
    # character (~132/sec for a typical LLM stream), flooding the frontend and
    # freezing the UI.  100ms = ~10 events/sec, smooth to the human eye
    # without flicker.
    REACT_STREAMING_EMIT_INTERVAL_MS: int = 100

    # Used by extensions/work_wechat
    WORK_WECHAT_WS_URL: str = "wss://openws.work.weixin.qq.com"
    WORK_WECHAT_WS_HEARTBEAT_SECONDS: int = 30
    WORK_WECHAT_WS_REQUEST_TIMEOUT_SECONDS: int = 10
    SYSTEM_TIME_ZONE: str = "Asia/Shanghai"
    OPENROUTER_APP_URL: str = "http://pivot-ai.org"
    OPENROUTER_APP_TITLE: str = "pivot"
    OPENROUTER_APP_CATEGORIES: str = "general-agent"

    # Automation scheduler
    AUTOMATION_SCHEDULER_ENABLED: bool = True
    AUTOMATION_SCHEDULER_SCAN_INTERVAL_SECONDS: int = 30
    AUTOMATION_SCHEDULER_MAX_CONCURRENT_RUNS: int = 5
    AUTOMATION_RUN_TIMEOUT_SECONDS: int = 300

    # Database
    DATABASE_URL: str = "sqlite:///./app.db"

    # Auth
    LOGIN_RATE_LIMIT_PER_MINUTE: int = 5

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
        default=100 * 1024 * 1024,
        validation_alias=AliasChoices("MAX_IMAGE_SIZE", "MAX_FILESIZE"),
    )
    MAX_FILE_SIZE: int = 100 * 1024 * 1024
    SKILL_IMPORT_MULTIPART_MAX_FILES: int = 10_000
    SKILL_IMPORT_MULTIPART_MAX_FIELDS: int = 10_000
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
        return cast("Any", Settings)(_env_file=str(env_file), ENV=env)

    # Fallback to .env in server dir
    base_env = server_dir / ".env"
    if base_env.exists():
        return cast("Any", Settings)(_env_file=str(base_env), ENV=env)

    return Settings(ENV=env)
