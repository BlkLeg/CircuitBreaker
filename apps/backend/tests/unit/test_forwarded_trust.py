"""X-Forwarded-Proto / -Host are evidence only when the peer is our own proxy.

SEC-13 established that model for X-Forwarded-For, but the cookie `Secure`
flag, the HSTS header, and the OAuth redirect URI each read their forwarded
header straight off the request from any peer. Same header, authoritative in
one module and forgeable in the next.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core import forwarded as core_forwarded


class _Headers(dict):
    def get(self, key, default=None):
        return super().get(key.lower(), default)


def _conn(peer: str, **headers) -> object:
    return SimpleNamespace(
        client=SimpleNamespace(host=peer),
        headers=_Headers({k.replace("_", "-").lower(): v for k, v in headers.items()}),
    )


@pytest.fixture(autouse=True)
def _trusted_proxy_is_10_0_0_0_8(monkeypatch):
    monkeypatch.setattr(core_forwarded.settings, "trusted_proxy_cidrs", ["10.0.0.0/8"])
    monkeypatch.setattr(core_forwarded, "_trusted_proxy_cache", None)


# ── forwarded_proto ──────────────────────────────────────────────────────────


def test_untrusted_peer_cannot_claim_https():
    conn = _conn("203.0.113.5", x_forwarded_proto="https")
    assert core_forwarded.forwarded_proto(conn, "http") == "http"


def test_trusted_proxy_can_report_https():
    conn = _conn("10.0.0.1", x_forwarded_proto="https")
    assert core_forwarded.forwarded_proto(conn, "http") == "https"


def test_trusted_proxy_chain_takes_the_original_scheme():
    conn = _conn("10.0.0.1", x_forwarded_proto="https, http")
    assert core_forwarded.forwarded_proto(conn, "http") == "https"


def test_missing_header_falls_back_to_the_default():
    assert core_forwarded.forwarded_proto(_conn("10.0.0.1"), "http") == "http"


# ── forwarded_host ───────────────────────────────────────────────────────────


def test_untrusted_peer_cannot_redirect_generated_urls():
    """This is the OAuth redirect_uri and the password-reset link."""
    conn = _conn("203.0.113.5", x_forwarded_host="attacker.example", host="cb.internal")
    assert core_forwarded.forwarded_host(conn, "cb.internal") == "cb.internal"


def test_trusted_proxy_can_set_the_public_host():
    conn = _conn("10.0.0.1", x_forwarded_host="cb.example.com", host="127.0.0.1:8000")
    assert core_forwarded.forwarded_host(conn, "127.0.0.1:8000") == "cb.example.com"


# ── peer classification ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("peer", "trusted"),
    [
        ("10.1.2.3", True),
        ("203.0.113.5", False),
        ("", False),
        ("not-an-ip", False),
    ],
)
def test_peer_classification(peer, trusted):
    assert core_forwarded.request_from_trusted_proxy(_conn(peer)) is trusted


def test_websocket_scope_peer_is_understood():
    """WebSocket handshakes arrive as a scope dict, not a Request."""
    scope = {
        "type": "websocket",
        "client": ("10.0.0.7", 51234),
        "headers": [(b"x-forwarded-proto", b"https")],
    }
    assert core_forwarded.forwarded_proto(scope) == "https"

    untrusted = {**scope, "client": ("203.0.113.5", 51234)}
    assert core_forwarded.forwarded_proto(untrusted, "ws") == "ws"


# ── the consumers ────────────────────────────────────────────────────────────


def test_cookie_secure_flag_ignores_an_untrusted_proto_claim():
    from app.core.auth_cookie import _is_secure_request

    request = SimpleNamespace(
        url=SimpleNamespace(scheme="http"),
        client=SimpleNamespace(host="203.0.113.5"),
        headers=_Headers({"x-forwarded-proto": "https"}),
    )
    assert _is_secure_request(request) is False


def test_hsts_is_not_triggered_by_an_untrusted_proto_claim():
    from app.middleware.security_headers import _is_secure_request

    request = SimpleNamespace(
        url=SimpleNamespace(scheme="http"),
        client=SimpleNamespace(host="203.0.113.5"),
        headers=_Headers({"x-forwarded-proto": "https"}),
    )
    assert _is_secure_request(request) is False


def test_ws_secure_check_ignores_an_untrusted_proto_claim():
    from app.core.auth_cookie import is_websocket_secure

    spoofed = {
        "type": "websocket",
        "scheme": "ws",
        "client": ("203.0.113.5", 4444),
        "headers": [(b"x-forwarded-proto", b"https")],
    }
    assert is_websocket_secure(spoofed) is False
