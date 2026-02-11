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
