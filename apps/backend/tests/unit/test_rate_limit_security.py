from __future__ import annotations

from types import SimpleNamespace

from app.core import forwarded as core_forwarded
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
    monkeypatch.setattr(core_forwarded, "_trusted_proxy_cache", None)

    identity = rate_limit.trusted_client_identity(_request("198.51.100.8", "203.0.113.9"))

    assert identity == "198.51.100.8"


def test_forwarded_for_is_used_from_configured_proxy(monkeypatch) -> None:
    monkeypatch.setattr(rate_limit.settings, "trusted_proxy_cidrs", ["10.10.0.0/16", "10.0.0.0/24"])
    monkeypatch.setattr(core_forwarded, "_trusted_proxy_cache", None)

    identity = rate_limit.trusted_client_identity(_request("10.10.0.5", "203.0.113.9, 10.0.0.1"))

    assert identity == "203.0.113.9"


def test_client_cannot_prepend_its_own_forwarded_for_behind_appending_proxy(monkeypatch) -> None:
    """The shipped nginx appends, so a caller's own header survives to the left.

    Reading left to right would hand that caller its own rate-limit key; the
    real address is the rightmost hop nginx wrote.
    """
    monkeypatch.setattr(rate_limit.settings, "trusted_proxy_cidrs", ["10.10.0.0/16"])
    monkeypatch.setattr(core_forwarded, "_trusted_proxy_cache", None)

    identity = rate_limit.trusted_client_identity(
        _request("10.10.0.5", "1.2.3.4, 203.0.113.9"),
    )

    assert identity == "203.0.113.9"


def test_rotating_spoofed_prefixes_cannot_change_the_rate_limit_key(monkeypatch) -> None:
    monkeypatch.setattr(rate_limit.settings, "trusted_proxy_cidrs", ["10.10.0.0/16"])
    monkeypatch.setattr(core_forwarded, "_trusted_proxy_cache", None)

    identities = {
        rate_limit.trusted_client_identity(_request("10.10.0.5", f"1.2.3.{n}, 203.0.113.9"))
        for n in range(1, 6)
    }

    assert identities == {"203.0.113.9"}


def test_all_trusted_chain_falls_back_to_peer(monkeypatch) -> None:
    monkeypatch.setattr(rate_limit.settings, "trusted_proxy_cidrs", ["10.10.0.0/16"])
    monkeypatch.setattr(core_forwarded, "_trusted_proxy_cache", None)

    identity = rate_limit.trusted_client_identity(_request("10.10.0.5", "10.10.0.7, 10.10.0.8"))

    assert identity == "10.10.0.5"


def test_invalid_forwarded_for_from_proxy_falls_back_to_peer(monkeypatch) -> None:
    monkeypatch.setattr(rate_limit.settings, "trusted_proxy_cidrs", ["10.10.0.0/16"])
    monkeypatch.setattr(core_forwarded, "_trusted_proxy_cache", None)

    identity = rate_limit.trusted_client_identity(_request("10.10.0.5", "not-an-ip"))

    assert identity == "10.10.0.5"
