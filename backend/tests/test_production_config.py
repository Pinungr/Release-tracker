import pytest

from app.config import get_settings


@pytest.mark.parametrize('secret', ['change-me-in-production', 'replace-with-a-long-random-string', 'short-secret', ' ' * 40])
def test_production_rejects_default_or_short_jwt(monkeypatch, secret):
    monkeypatch.setenv('ENVIRONMENT', 'production')
    monkeypatch.setenv('JWT_SECRET', secret)
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match='JWT_SECRET'):
            get_settings()
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize('environment,secret', [
    ('production', '7f55bb682d579b13ac77c74a5fa4e9fecb91c5e265ea8423'),
    ('development', 'change-me-in-production'),
    ('development', 'replace-with-a-long-random-string'),
])
def test_valid_production_and_local_development_config(monkeypatch, environment, secret):
    monkeypatch.setenv('ENVIRONMENT', environment)
    monkeypatch.setenv('JWT_SECRET', secret)
    get_settings.cache_clear()
    try:
        assert get_settings().jwt_secret == secret
    finally:
        get_settings.cache_clear()
