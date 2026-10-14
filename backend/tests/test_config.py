import pytest

from app.core.config import Settings


def test_environment_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/x")
    monkeypatch.setenv("REDIS_URL", "redis://cache:6379/1")
    monkeypatch.setenv("LOG_JSON", "true")

    s = Settings()

    assert s.database_url == "postgresql+asyncpg://u:p@db:5432/x"
    assert s.redis_url == "redis://cache:6379/1"
    assert s.log_json is True


def test_unknown_environment_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging-ish")

    with pytest.raises(ValueError):
        Settings()
