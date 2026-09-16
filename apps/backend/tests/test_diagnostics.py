"""Unit tests for normalized install/runtime diagnostics."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from app.services.diagnostics import (
    EXPECTED_WORKER_HEARTBEATS,
    bound_evidence,
    collect_diagnostics,
)

_REQUIRED_KEYS = frozenset(
    {
        "component",
        "check",
        "status",
        "severity",
        "evidence",
        "remediation",
        "safe_to_retry",
    }
)
_VALID_STATUS = frozenset({"pass", "warn", "fail", "unknown", "skipped"})
_VALID_SEVERITY = frozenset({"info", "warning", "error", "critical"})


def _minimal_identity(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "schema_version": 1,
        "mode": "mono",
        "version": "0.4.2",
        "installed_at": "2026-09-16T12:00:00Z",
    }
    base.update(overrides)
    return base


def _write_fresh_heartbeats(data_dir: Path) -> None:
    now = str(time.time())
    for name in EXPECTED_WORKER_HEARTBEATS:
        (data_dir / f"{name}.healthy").write_text(now, encoding="utf-8")


async def _pin_deps(monkeypatch: pytest.MonkeyPatch, *, db: str = "ok", redis: str = "ok") -> None:
    async def _probe() -> dict[str, str]:
        return {"db": db, "redis": redis}

    monkeypatch.setattr("app.core.health.probe_dependencies", _probe)

    from app.core.health import HealthSnapshot, HealthState

    async def _current_health(*, max_age_s: float | None = None) -> HealthSnapshot:
        return HealthSnapshot(
            state=HealthState.READY if db == "ok" else HealthState.NOT_READY,
            lifecycle="ready",
            checks={"db": db, "redis": redis},
            degraded=() if redis == "ok" else ("redis",),
            writes_permitted=db == "ok",
            reason=None if db == "ok" else "required dependency unavailable: db",
            observed_at=0.0,
        )

    monkeypatch.setattr("app.core.health.current_health", _current_health)


@pytest.mark.asyncio
async def test_normalized_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every check matches the diagnostic-result schema shape."""
    monkeypatch.delenv("CB_IDENTITY_PATH", raising=False)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_fresh_heartbeats(data_dir)
    (data_dir / "install-identity.json").write_text(
        json.dumps(_minimal_identity(data_dir=str(data_dir))),
        encoding="utf-8",
    )
    await _pin_deps(monkeypatch)

    checks = await collect_diagnostics(data_dir=data_dir, home=tmp_path / "nouser")
    assert checks
    for item in checks:
        assert _REQUIRED_KEYS <= set(item.keys())
        assert set(item.keys()) <= _REQUIRED_KEYS
        assert item["status"] in _VALID_STATUS
        assert item["severity"] in _VALID_SEVERITY
        assert isinstance(item["evidence"], str)
        assert isinstance(item["remediation"], str)
        assert isinstance(item["safe_to_retry"], bool)
        assert len(item["evidence"]) <= 500


@pytest.mark.asyncio
async def test_missing_identity_is_fail_or_warn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing install identity produces a fail or warn identity check."""
    monkeypatch.delenv("CB_IDENTITY_PATH", raising=False)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_fresh_heartbeats(data_dir)
    await _pin_deps(monkeypatch)

    checks = await collect_diagnostics(data_dir=data_dir, home=tmp_path / "nouser")
    identity = [c for c in checks if c["component"] == "identity"]
    assert len(identity) == 1
    assert identity[0]["status"] in {"fail", "warn"}
    assert identity[0]["check"] == "valid"
    assert identity[0]["remediation"]


@pytest.mark.asyncio
async def test_evidence_never_contains_vault_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Evidence stays free of obvious secrets when CB_VAULT_KEY is set."""
    secret = "unit-test-vault-key-DO-NOT-LEAK-9f3a"
    monkeypatch.setenv("CB_VAULT_KEY", secret)
    monkeypatch.delenv("CB_IDENTITY_PATH", raising=False)

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_fresh_heartbeats(data_dir)
    # Put the vault key into a field that would otherwise surface in evidence.
    (data_dir / "install-identity.json").write_text(
        json.dumps(_minimal_identity(version=secret)),
        encoding="utf-8",
    )
    await _pin_deps(monkeypatch)

    checks = await collect_diagnostics(data_dir=data_dir, home=tmp_path / "nouser")
    blob = "\n".join(c["evidence"] for c in checks)
    assert secret not in blob
    assert "[REDACTED]" in blob

    # Direct redaction contract for common secret line patterns.
    redacted = bound_evidence(f"token=abc\npassword=hunter2\nCB_VAULT_KEY={secret}\nplain")
    assert secret not in redacted
    assert "hunter2" not in redacted
    assert "token=abc" not in redacted
    assert "[REDACTED]" in redacted
    assert "plain" in redacted


@pytest.mark.asyncio
async def test_storage_check_uses_temp_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Storage free_space check runs against the provided data dir."""
    monkeypatch.delenv("CB_IDENTITY_PATH", raising=False)
    data_dir = tmp_path / "data-volume"
    data_dir.mkdir()
    _write_fresh_heartbeats(data_dir)
    (data_dir / "install-identity.json").write_text(
        json.dumps(_minimal_identity()),
        encoding="utf-8",
    )
    await _pin_deps(monkeypatch)

    checks = await collect_diagnostics(data_dir=data_dir, home=tmp_path / "nouser")
    storage = [c for c in checks if c["component"] == "storage" and c["check"] == "free_space"]
    assert len(storage) == 1
    assert storage[0]["status"] in {"pass", "warn"}
    assert str(data_dir) in storage[0]["evidence"]
    assert "free_bytes=" in storage[0]["evidence"]


def test_bound_evidence_caps_length() -> None:
    long = "x" * 2000
    out = bound_evidence(long)
    assert len(out) <= 500
    assert out.endswith("…")
