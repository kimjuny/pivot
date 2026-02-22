import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseSettings


class Settings(BaseSettings):
    # App Settings
    ENV: str = "development"
    PROJECT_NAME: str = "Pivot Server"

    # Database
    DATABASE_URL: str = "sqlite:///./app.db"

    # LLM Flags
    LLM_DOUBAO: bool = False
    LLM_GLM: bool = False

    # LLM API Keys
    DOUBAO_SEED_API_KEY: str | None = None
    GLM_API_KEY: str | None = None

    # Sandbox Configuration
    # Execution mode for tools: "sidecar" (isolated container) or "local" (in-process)
    SANDBOX_MODE: str = "sidecar"
    # Path to podman socket (used in sidecar mode)
    # Platform defaults:
    #   - macOS (podman-machine): /run/podman/podman.sock (mounted from host)
    #   - Linux (rootful): /run/podman/podman.sock
    #   - Linux (rootless): /run/user/<UID>/podman/podman.sock
    #   - Windows (WSL2): Same as Linux rootless
    PODMAN_SOCKET_PATH: str = "/run/podman/podman.sock"
    # Timeout for sidecar container execution in seconds
    SIDECAR_TIMEOUT_SECONDS: int = 60
    # Network mode for sidecar containers (None for isolated, "host" for minimal overhead)
    SIDECAR_NETWORK_MODE: str | None = None
    # Base image for sidecar containers (defaults to current backend image)
    SIDECAR_BASE_IMAGE: str | None = None
    # Resource limits for sidecar containers
    # Memory limit in bytes (e.g., "256m", "1g", None for unlimited)
    SIDECAR_MEMORY_LIMIT: str | None = None
    # CPU quota in microseconds per period (e.g., 50000 = 50% of CPU, None for unlimited)
    SIDECAR_CPU_QUOTA: int | None = None

    class Config:  # type: ignore
        env_file = ".env"


@lru_cache
def get_settings():
    env = os.getenv("ENV", "development")

    # server/app/config.py -> server/
    server_dir = Path(__file__).resolve().parent.parent
    env_file = server_dir / f".env.{env}"

    # If specific env file exists, use it
    if env_file.exists():
        return Settings(_env_file=str(env_file))  # type: ignore

    # Fallback to .env in server dir
    base_env = server_dir / ".env"
    if base_env.exists():
        return Settings(_env_file=str(base_env))  # type: ignore

    return Settings()
