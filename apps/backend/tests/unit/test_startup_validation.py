from __future__ import annotations

import pytest

from app.core import startup_validation


def test_validate_startup_secrets_rejects_empty_session_secret() -> None:
    errors = startup_validation.validate_startup_secrets(jwt_secret="", vault_key=None)

    assert errors == ("JWT/session signing secret is missing or empty",)


def test_validate_startup_secrets_rejects_placeholders_without_echoing_values() -> None:
    errors = startup_validation.validate_startup_secrets(
        jwt_secret="change_me",
        vault_key="secret",
    )

    assert "placeholder" in errors[0]
    assert "change_me" not in errors[0]
    assert "secret" not in errors[1].lower()


@pytest.mark.asyncio
async def test_validate_core_dependencies_fails_closed_by_default(monkeypatch) -> None:
    monkeypatch.delenv("CB_ALLOW_DEGRADED_DEPENDENCIES", raising=False)
    monkeypatch.setattr(startup_validation.settings, "rate_limit_storage_url", "")
    monkeypatch.setattr(startup_validation.settings, "egress_proxy_url", "")

    with pytest.raises(RuntimeError) as exc_info:
        await startup_validation.validate_core_dependencies(None, False)

    message = str(exc_info.value)
    assert "Redis is unavailable" in message
    assert "NATS is unavailable" in message
    assert "CB_EGRESS_PROXY_URL is required" in message


@pytest.mark.asyncio
async def test_validate_core_dependencies_requires_egress_proxy(monkeypatch) -> None:
    monkeypatch.delenv("CB_ALLOW_DEGRADED_DEPENDENCIES", raising=False)
    monkeypatch.setattr(startup_validation.settings, "rate_limit_storage_url", "")
    monkeypatch.setattr(startup_validation.settings, "egress_proxy_url", "")

    with pytest.raises(RuntimeError) as exc_info:
        await startup_validation.validate_core_dependencies(object(), True)

    assert "CB_EGRESS_PROXY_URL is required" in str(exc_info.value)


@pytest.mark.asyncio
async def test_validate_core_dependencies_rejects_memory_rate_limit_storage(monkeypatch) -> None:
    monkeypatch.delenv("CB_ALLOW_DEGRADED_DEPENDENCIES", raising=False)
    monkeypatch.setattr(startup_validation.settings, "rate_limit_storage_url", "memory://")
    monkeypatch.setattr(startup_validation.settings, "egress_proxy_url", "http://127.0.0.1:3128")

    with pytest.raises(RuntimeError) as exc_info:
        await startup_validation.validate_core_dependencies(object(), True)

    assert "shared Redis storage" in str(exc_info.value)


@pytest.mark.asyncio
async def test_validate_core_dependencies_allows_explicit_degraded_mode(monkeypatch) -> None:
    monkeypatch.setenv("CB_ALLOW_DEGRADED_DEPENDENCIES", "true")

    await startup_validation.validate_core_dependencies(None, False)
