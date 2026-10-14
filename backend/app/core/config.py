"""Application settings, read from environment variables (and an optional .env file).

Every process (API, worker, migrations) builds its settings from here, so there is one
place that defines what can be configured and what the defaults are.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["local", "test", "production"] = "local"
    log_level: str = "INFO"
    # JSON logs in containers (easy to search); readable console logs on a laptop.
    log_json: bool = False

    # Defaults point at the ports docker compose publishes on the host, so tests run
    # from a laptop work after `make up`. Inside compose these are overridden.
    database_url: str = "postgresql+asyncpg://campaign:campaign@localhost:5433/campaign_manager"
    db_pool_size: int = 10
    db_max_overflow: int = 10
    redis_url: str = "redis://localhost:6380/0"

    # Where outbound calls are sent. Always the mock Sarvam server in this project.
    sarvam_base_url: str = "http://localhost:9000"

    # How long a readiness check waits for Postgres or Redis before calling it down.
    health_check_timeout_s: float = 2.0

    worker_heartbeat_interval_s: float = 5.0
    worker_heartbeat_file: str = "/tmp/worker-heartbeat"


@lru_cache
def get_settings() -> Settings:
    return Settings()
