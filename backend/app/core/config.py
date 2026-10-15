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
    sarvam_connect_timeout_s: float = 2.0
    sarvam_read_timeout_s: float = 10.0
    # Base URL Sarvam (the mock) uses to reach our webhook.
    public_base_url: str = "http://localhost:8000"

    # Secrets. The defaults are for local development only; set real values in production.
    jwt_secret: str = "local-dev-jwt-secret-change-me-0123456789"
    jwt_ttl_minutes: int = 720
    # 32 bytes, base64. Encrypts Sarvam API keys at rest.
    encryption_key: str = "bG9jYWwtZGV2LWVuY3J5cHRpb24ta2V5LTMyYnl0ZXM="
    webhook_signing_secret: str = "local-dev-webhook-secret"

    # First superadmin, created by `python -m app.seed` if missing.
    seed_superadmin_email: str = "admin@example.com"
    seed_superadmin_password: str = "admin12345"
    # Also create a demo organisation, workspace, agent and connection.
    seed_demo_data: bool = True

    # How long a readiness check waits for Postgres or Redis before calling it down.
    health_check_timeout_s: float = 2.0

    worker_heartbeat_interval_s: float = 5.0
    worker_heartbeat_file: str = "/tmp/worker-heartbeat"

    # Execution engine
    dispatch_slots: int = 32  # concurrent dispatch loops per worker process
    # Safety margin added to the per-second spacing. Sarvam counts calls when they arrive, and
    # the network adds jitter between our send and their count; the margin absorbs it. Costs
    # about margin/1000 of throughput (100 ms: we run at ~91% of the limit).
    rate_margin_ms: int = 100
    late_tolerance_ms: int = 20  # a send more than this late is cancelled, never sent late
    reserve_horizon_ms: int = 1000  # how far ahead a send slot may be booked
    lease_seconds: int = 60  # how long a claimed contact belongs to one worker
    webhook_timeout_s: int = 900  # no outcome after this long: attempt is "lost"
    scheduler_tick_s: float = 1.0
    phone_lock_ttl_s: int = 1800

    # CSV upload
    default_phone_region: str = "IN"
    max_upload_bytes: int = 20 * 1024 * 1024
    max_upload_rows: int = 200_000


@lru_cache
def get_settings() -> Settings:
    return Settings()
