from __future__ import annotations

from types import SimpleNamespace

from app.core import rate_limit


class _Headers(dict):
    def get(self, key: str, default: object = None) -> object:
        return super().get(key.lower(), default)


def _request(peer: str, forwarded: str | None = None) -> object:
    headers = _Headers()
    if forwarded is not None:
        headers["x-forwarded-for"] = forwarded
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)


def test_spoofed_forwarded_for_is_ignored_from_untrusted_peer(monkeypatch) -> None:
    monkeypatch.setattr(rate_limit.settings, "trusted_proxy_cidrs", ["127.0.0.1/32"])
    monkeypatch.setattr(rate_limit, "_trusted_proxy_cache", None)

    identity = rate_limit.trusted_client_identity(_request("198.51.100.8", "203.0.113.9"))

    assert identity == "198.51.100.8"


def test_forwarded_for_is_used_from_configured_proxy(monkeypatch) -> None:
    monkeypatch.setattr(rate_limit.settings, "trusted_proxy_cidrs", ["10.10.0.0/16"])
    monkeypatch.setattr(rate_limit, "_trusted_proxy_cache", None)

    identity = rate_limit.trusted_client_identity(_request("10.10.0.5", "203.0.113.9, 10.0.0.1"))

    assert identity == "203.0.113.9"


def test_invalid_forwarded_for_from_proxy_falls_back_to_peer(monkeypatch) -> None:
    monkeypatch.setattr(rate_limit.settings, "trusted_proxy_cidrs", ["10.10.0.0/16"])
    monkeypatch.setattr(rate_limit, "_trusted_proxy_cache", None)

    identity = rate_limit.trusted_client_identity(_request("10.10.0.5", "not-an-ip"))

    assert identity == "10.10.0.5"
