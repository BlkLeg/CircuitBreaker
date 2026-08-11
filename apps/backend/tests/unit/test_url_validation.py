from __future__ import annotations

import socket

import httpx
import pytest

from app.core.url_validation import (
    EGRESS_PROXY_POLICY,
    LAN_INTEGRATION_POLICY,
    WEBHOOK_POLICY,
    outbound_async_client,
    safe_async_request,
    validate_outbound_url,
    validate_redirect_target,
)


def _addrinfo(*addresses: str) -> list[tuple[int, int, int, str, tuple[str, int]]]:
    rows = []
    for address in addresses:
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        rows.append((family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 443)))
    return rows


def test_webhook_policy_rejects_loopback_link_local_and_private_literals() -> None:
    for url in (
        "https://127.0.0.1/hook",
        "https://[::1]/hook",
        "https://169.254.169.254/latest/meta-data",
        "https://10.0.0.5/hook",
    ):
        with pytest.raises(ValueError):
            validate_outbound_url(url, WEBHOOK_POLICY)


def test_webhook_policy_rejects_encoded_ipv4_literals(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(host: str, *_args: object, **_kwargs: object) -> object:
        assert host == "2130706433"
        return _addrinfo("127.0.0.1")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(ValueError):
        validate_outbound_url("https://2130706433/hook", WEBHOOK_POLICY)


def test_webhook_policy_rejects_mixed_dns_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(_host: str, *_args: object, **_kwargs: object) -> object:
        return _addrinfo("93.184.216.34", "10.0.0.9")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(ValueError):
        validate_outbound_url("https://webhook.example/hook", WEBHOOK_POLICY)


def test_lan_integration_policy_allows_private_but_not_metadata() -> None:
    validate_outbound_url("https://192.168.1.1:8443", LAN_INTEGRATION_POLICY)
    validate_outbound_url("https://[fd00::10]", LAN_INTEGRATION_POLICY)

    for url in ("https://169.254.169.254", "https://203.0.113.10"):
        with pytest.raises(ValueError):
            validate_outbound_url(url, LAN_INTEGRATION_POLICY)


def test_lan_integration_policy_allows_unresolved_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_getaddrinfo(_host: str, *_args: object, **_kwargs: object) -> object:
        raise socket.gaierror("offline")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    validated = validate_outbound_url("https://pve.example.invalid:8006", LAN_INTEGRATION_POLICY)

    assert validated.addresses == ()


def test_redirect_validation_rejects_private_target() -> None:
    with pytest.raises(ValueError):
        validate_redirect_target("https://example.com/source", "http://10.0.0.4/internal")


def test_egress_proxy_policy_allows_loopback_but_rejects_metadata() -> None:
    validate_outbound_url("http://127.0.0.1:3128", EGRESS_PROXY_POLICY)

    with pytest.raises(ValueError):
        validate_outbound_url("http://169.254.169.254:3128", EGRESS_PROXY_POLICY)


def test_outbound_async_client_uses_configured_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            seen.update(kwargs)

    monkeypatch.setattr(
        "app.core.url_validation.configured_egress_proxy_url",
        lambda: "http://127.0.0.1:3128",
    )
    monkeypatch.setattr("app.core.url_validation.httpx.AsyncClient", FakeClient)

    outbound_async_client()

    assert seen["proxy"] == "http://127.0.0.1:3128"
    assert seen["trust_env"] is False


@pytest.mark.asyncio
async def test_safe_async_request_validates_redirect_before_second_hop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def fake_getaddrinfo(host: str, *_args: object, **_kwargs: object) -> object:
        if host == "public.example":
            return _addrinfo("93.184.216.34")
        if host == "internal.example":
            return _addrinfo("10.0.0.8")
        raise AssertionError(host)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://internal.example/secret"})

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError):
            await safe_async_request(
                client,
                "GET",
                "https://public.example/start",
                max_redirects=1,
            )

    assert seen == ["https://public.example/start"]
