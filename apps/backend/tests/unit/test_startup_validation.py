from __future__ import annotations

import pytest

from app.core import startup_validation


@pytest.fixture(autouse=True)
def _no_ambient_direct_egress_opt_out(monkeypatch):
    """The opt-out must never come from the developer's own shell."""
    monkeypatch.delenv("CB_ALLOW_DIRECT_EGRESS", raising=False)


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


# ── Egress policy ────────────────────────────────────────────────────────────
# A proxy-less homelab host has no correct value for CB_EGRESS_PROXY_URL, and
# leaving it empty stops the backend booting. CB_ALLOW_DIRECT_EGRESS records
# that "no proxy on this host" is a decision rather than an omission, and
# waives only the proxy requirement — every other gate still fails closed.


@pytest.mark.asyncio
async def test_configured_egress_proxy_is_not_reported_as_an_error(monkeypatch) -> None:
    """A validated proxy URL is a success value, not a failure message."""
    monkeypatch.delenv("CB_ALLOW_DEGRADED_DEPENDENCIES", raising=False)
    monkeypatch.setattr(startup_validation.settings, "rate_limit_storage_url", "")
    monkeypatch.setattr(startup_validation.settings, "egress_proxy_url", "http://127.0.0.1:3128")

    await startup_validation.validate_core_dependencies(object(), True)


@pytest.mark.asyncio
async def test_invalid_egress_proxy_still_fails(monkeypatch) -> None:
    monkeypatch.delenv("CB_ALLOW_DEGRADED_DEPENDENCIES", raising=False)
    monkeypatch.setattr(startup_validation.settings, "rate_limit_storage_url", "")
    monkeypatch.setattr(startup_validation.settings, "egress_proxy_url", "not-a-url")

    with pytest.raises(RuntimeError) as exc_info:
        await startup_validation.validate_core_dependencies(object(), True)

    assert "CB_EGRESS_PROXY_URL is invalid" in str(exc_info.value)


@pytest.mark.asyncio
async def test_direct_egress_opt_out_waives_the_proxy_requirement(monkeypatch) -> None:
    monkeypatch.delenv("CB_ALLOW_DEGRADED_DEPENDENCIES", raising=False)
    monkeypatch.setenv("CB_ALLOW_DIRECT_EGRESS", "true")
    monkeypatch.setattr(startup_validation.settings, "rate_limit_storage_url", "")
    monkeypatch.setattr(startup_validation.settings, "egress_proxy_url", "")

    await startup_validation.validate_core_dependencies(object(), True)


@pytest.mark.asyncio
async def test_direct_egress_opt_out_does_not_waive_the_other_gates(monkeypatch) -> None:
    """This is the whole point of a separate switch from degraded mode."""
    monkeypatch.delenv("CB_ALLOW_DEGRADED_DEPENDENCIES", raising=False)
    monkeypatch.setenv("CB_ALLOW_DIRECT_EGRESS", "true")
    monkeypatch.setattr(startup_validation.settings, "rate_limit_storage_url", "memory://")
    monkeypatch.setattr(startup_validation.settings, "egress_proxy_url", "")

    with pytest.raises(RuntimeError) as exc_info:
        await startup_validation.validate_core_dependencies(None, False)

    message = str(exc_info.value)
    assert "shared Redis storage" in message
    assert "Redis is unavailable" in message
    assert "NATS is unavailable" in message
    assert "CB_EGRESS_PROXY_URL" not in message


@pytest.mark.asyncio
async def test_direct_egress_opt_out_does_not_excuse_a_malformed_proxy(monkeypatch) -> None:
    """Opting out of a proxy is a choice; a broken proxy value is a mistake."""
    monkeypatch.delenv("CB_ALLOW_DEGRADED_DEPENDENCIES", raising=False)
    monkeypatch.setenv("CB_ALLOW_DIRECT_EGRESS", "true")
    monkeypatch.setattr(startup_validation.settings, "rate_limit_storage_url", "")
    monkeypatch.setattr(startup_validation.settings, "egress_proxy_url", "not-a-url")

    with pytest.raises(RuntimeError) as exc_info:
        await startup_validation.validate_core_dependencies(object(), True)

    assert "CB_EGRESS_PROXY_URL is invalid" in str(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["false", "0", "no", "", "  "])
async def test_direct_egress_opt_out_must_be_explicit(monkeypatch, value: str) -> None:
    monkeypatch.delenv("CB_ALLOW_DEGRADED_DEPENDENCIES", raising=False)
    monkeypatch.setenv("CB_ALLOW_DIRECT_EGRESS", value)
    monkeypatch.setattr(startup_validation.settings, "rate_limit_storage_url", "")
    monkeypatch.setattr(startup_validation.settings, "egress_proxy_url", "")

    with pytest.raises(RuntimeError) as exc_info:
        await startup_validation.validate_core_dependencies(object(), True)

    assert "CB_EGRESS_PROXY_URL is required" in str(exc_info.value)
