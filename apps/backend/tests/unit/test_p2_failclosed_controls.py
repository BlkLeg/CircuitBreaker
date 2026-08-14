"""P2 controls that previously failed open or ran silently.

Each of these was a control that existed on paper: the audit-chain lock caught
its own exception, the OIDC validator was a weaker copy of the shared one, and
the tenant seed script rewrote authorization-relevant data on a bare
invocation.
"""

from __future__ import annotations

import pytest

# ── Audit chain serialisation lock ───────────────────────────────────────────


def test_audit_chain_lock_raises_instead_of_swallowing_on_postgres():
    """Losing this lock forks the hash chain, which later reads as tampering."""
    from app.core.audit_chain import lock_audit_chain

    class _Bind:
        dialect = type("D", (), {"name": "postgresql"})()

    class _Session:
        def get_bind(self):
            return _Bind()

        def execute(self, _stmt):
            raise RuntimeError("deadlock detected")

    with pytest.raises(RuntimeError, match="without its serialisation lock"):
        lock_audit_chain(_Session())


def test_audit_chain_lock_is_a_no_op_on_sqlite():
    """SQLite has no advisory locks and is single-writer — that is by design, not failure."""
    from app.core.audit_chain import lock_audit_chain

    executed = []

    class _Bind:
        dialect = type("D", (), {"name": "sqlite"})()

    class _Session:
        def get_bind(self):
            return _Bind()

        def execute(self, stmt):  # pragma: no cover - must not be reached
            executed.append(stmt)

    lock_audit_chain(_Session())
    assert executed == []


# ── OIDC uses the shared outbound validator ──────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/.well-known/openid-configuration",
        "http://[::1]/.well-known/openid-configuration",
        "http://169.254.169.254/latest/meta-data/",
        "ftp://idp.example.com/x",
    ],
)
def test_oidc_rejects_loopback_linklocal_and_bad_schemes(url):
    from fastapi import HTTPException

    from app.api.auth_oauth import _validate_oidc_url

    with pytest.raises(HTTPException) as exc:
        _validate_oidc_url(url, "OIDC discovery_url")
    assert exc.value.status_code == 400


def test_oidc_policy_still_allows_an_on_prem_idp():
    """RFC1918 must keep working — on-prem identity providers are the common case."""
    from app.core.url_validation import OIDC_POLICY

    assert OIDC_POLICY.allow_private is True
    assert OIDC_POLICY.allow_local is False


# ── LAN integrations re-validate at connect time ─────────────────────────────


@pytest.mark.parametrize("target", ["https://127.0.0.1", "https://169.254.169.254"])
def test_validate_lan_target_refuses_loopback_and_link_local(target):
    from app.core.url_validation import validate_lan_target

    with pytest.raises(ConnectionError):
        validate_lan_target(target, "Test host")


def test_validate_lan_target_allows_a_private_address():
    from app.core.url_validation import validate_lan_target

    validate_lan_target("https://192.168.1.10", "Test host")


# ── Tenant seed script requires confirmation ─────────────────────────────────


def test_tenant_seed_refuses_without_explicit_confirmation(monkeypatch):
    """Stamping tenant ids activates the tenant read rule and can hide data."""
    from app.scripts.seed_default_team import seed_default_tenant

    monkeypatch.delenv("CB_CONFIRM_TENANT_SEED", raising=False)
    with pytest.raises(SystemExit) as exc:
        seed_default_tenant()
    assert "without confirmation" in str(exc.value)


def test_tenant_seed_confirmation_can_be_given_by_env(monkeypatch):
    """Confirmed path must get past the guard (DB work is exercised elsewhere)."""
    import app.scripts.seed_default_team as seed_mod

    monkeypatch.setenv("CB_CONFIRM_TENANT_SEED", "1")

    reached = []

    class _Boom:
        def __call__(self):
            reached.append(True)
            raise AssertionError("stop after the guard")

    monkeypatch.setattr(seed_mod, "SessionLocal", _Boom())
    with pytest.raises(AssertionError, match="stop after the guard"):
        seed_mod.seed_default_tenant()
    assert reached == [True]
