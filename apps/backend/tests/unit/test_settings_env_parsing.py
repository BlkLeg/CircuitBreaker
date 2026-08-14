"""List-valued settings must survive plain comma-separated env values.

pydantic-settings JSON-decodes any complex (list/dict) field inside
EnvSettingsSource *before* a `mode="before"` field validator ever runs, so a
`CB_TRUSTED_PROXY_CIDRS=127.0.0.1/32,::1/128` line — exactly what install.sh
writes to /etc/circuitbreaker/.env — raised SettingsError at import time and
killed the backend on boot. The validators below only get a say once the field
opts out of that decode.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings


@pytest.fixture(autouse=True)
def _no_env_file(monkeypatch, tmp_path):
    """Keep a developer's local .env out of these assertions."""
    monkeypatch.chdir(tmp_path)
    for var in ("CB_TRUSTED_PROXY_CIDRS", "TRUSTED_PROXY_CIDRS", "CORS_ORIGINS"):
        monkeypatch.delenv(var, raising=False)


def test_trusted_proxy_cidrs_accepts_comma_separated_env(monkeypatch):
    monkeypatch.setenv("CB_TRUSTED_PROXY_CIDRS", "127.0.0.1/32,::1/128")
    assert Settings().trusted_proxy_cidrs == ["127.0.0.1/32", "::1/128"]


def test_trusted_proxy_cidrs_accepts_single_cidr_env(monkeypatch):
    monkeypatch.setenv("CB_TRUSTED_PROXY_CIDRS", "10.0.0.0/8")
    assert Settings().trusted_proxy_cidrs == ["10.0.0.0/8"]


def test_trusted_proxy_cidrs_accepts_json_env(monkeypatch):
    monkeypatch.setenv("CB_TRUSTED_PROXY_CIDRS", '["10.0.0.0/8", "192.168.0.0/16"]')
    assert Settings().trusted_proxy_cidrs == ["10.0.0.0/8", "192.168.0.0/16"]


def test_trusted_proxy_cidrs_empty_env_falls_back_to_loopback(monkeypatch):
    """setup.sh renders an unset override as a bare `CB_TRUSTED_PROXY_CIDRS=`."""
    monkeypatch.setenv("CB_TRUSTED_PROXY_CIDRS", "")
    assert Settings().trusted_proxy_cidrs == ["127.0.0.1/32", "::1/128"]


def test_trusted_proxy_cidrs_unset_uses_default():
    assert Settings().trusted_proxy_cidrs == ["127.0.0.1/32", "::1/128"]


def test_cors_origins_accepts_comma_separated_env(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173")
    assert Settings().cors_origins == ["http://localhost:3000", "http://localhost:5173"]


def test_cors_origins_accepts_json_env(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", '["http://localhost:3000"]')
    assert Settings().cors_origins == ["http://localhost:3000"]


def test_cors_origins_empty_env_is_empty_list(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "")
    assert Settings().cors_origins == []
