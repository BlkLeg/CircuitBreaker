"""Tests for log injection hardening helpers."""

from app.core.log_sanitize import safe_log_fragment
from app.core.security import client_hash_password, legacy_client_wire_hash_v1


def test_safe_log_fragment_strips_control_chars() -> None:
    dirty = "line1\nForged entry: user=admin\r\nline2"
    out = safe_log_fragment(dirty)
    assert "\n" not in out
    assert "\r" not in out


def test_safe_log_fragment_redacts_secret_like_kv() -> None:
    s = safe_log_fragment("error: api_key=supersecret&ok=1")
    assert "supersecret" not in s
    assert "<redacted>" in s


def test_client_hash_v2_stable_and_prefixed() -> None:
    h = client_hash_password("TestPassword123!", "circuitbreaker-salt-v1")
    assert h == client_hash_password("TestPassword123!", "circuitbreaker-salt-v1")
    assert h.startswith("v2.")
    assert len(h) == len("v2.") + 64


def test_legacy_v1_wire_hash_is_64_hex() -> None:
    h = legacy_client_wire_hash_v1("x", "y")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)
