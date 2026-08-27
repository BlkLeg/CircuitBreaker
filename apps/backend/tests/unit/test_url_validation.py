from __future__ import annotations

import ipaddress
import socket

import httpx
import pytest

from app.core.url_validation import (
    EGRESS_PROXY_POLICY,
    LAN_INTEGRATION_POLICY,
    WEBHOOK_POLICY,
    outbound_async_client,
    pinned_request,
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
    seen: list[tuple[str, str | None]] = []

    def fake_getaddrinfo(host: str, *_args: object, **_kwargs: object) -> object:
        if host == "public.example":
            return _addrinfo("93.184.216.34")
        if host == "internal.example":
            return _addrinfo("10.0.0.8")
        raise AssertionError(host)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers.get("host")))
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

    # Exactly one request left the process, and it was dialed at the address the
    # first hop validated rather than at the name.  The private redirect target
    # was rejected before any second request was built.
    assert seen == [("https://93.184.216.34/start", "public.example")]


class _ResolvingTransport(httpx.AsyncBaseTransport):
    """A transport that resolves the request host the way a real one does.

    httpx hands the URL's host to the connection pool, which resolves it at
    connect time.  This stand-in reproduces that second lookup so a test can
    observe which address the request would actually have been dialed at.
    """

    def __init__(self) -> None:
        self.dialed: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        try:
            ipaddress.ip_address(host)
        except ValueError:
            infos = socket.getaddrinfo(
                host,
                request.url.port or 443,
                family=0,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
            self.dialed.append(str(infos[0][4][0]))
        else:
            self.dialed.append(host)
        return httpx.Response(200, request=request)


@pytest.mark.asyncio
async def test_safe_async_request_survives_dns_rebinding_between_check_and_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A TTL-0 answer that flips to loopback after validation must not be dialed."""

    answers = iter([_addrinfo("93.184.216.34"), _addrinfo("127.0.0.1")])

    def fake_getaddrinfo(_host: str, *_args: object, **_kwargs: object) -> object:
        return next(answers, _addrinfo("127.0.0.1"))

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    transport = _ResolvingTransport()
    async with httpx.AsyncClient(transport=transport) as client:
        response = await safe_async_request(client, "POST", "https://webhook.example/hook")

    assert response.status_code == 200
    assert transport.dialed == ["93.184.216.34"]


@pytest.mark.asyncio
async def test_safe_async_request_keeps_host_and_sni_when_pinning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_getaddrinfo(_host: str, *_args: object, **_kwargs: object) -> object:
        return _addrinfo("93.184.216.34")

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["host"] = request.headers.get("host")
        seen["sni"] = request.extensions.get("sni_hostname")
        return httpx.Response(200)

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await safe_async_request(client, "GET", "https://webhook.example/hook")

    assert seen["url"] == "https://93.184.216.34/hook"
    assert seen["host"] == "webhook.example"
    assert seen["sni"] == "webhook.example"


@pytest.mark.asyncio
async def test_safe_async_request_brackets_ipv6_and_keeps_a_nondefault_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pin must survive an IPv6 answer and a port the scheme does not default to."""

    seen: dict[str, object] = {}

    def fake_getaddrinfo(_host: str, *_args: object, **_kwargs: object) -> object:
        return _addrinfo("2606:2800:220:1:248:1893:25c8:1946")

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["host"] = request.headers.get("host")
        seen["sni"] = request.extensions.get("sni_hostname")
        return httpx.Response(200)

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await safe_async_request(client, "GET", "https://webhook.example:8443/hook")

    assert seen["url"] == "https://[2606:2800:220:1:248:1893:25c8:1946]:8443/hook"
    assert seen["host"] == "webhook.example:8443"
    assert seen["sni"] == "webhook.example"


@pytest.mark.asyncio
async def test_safe_async_request_keeps_the_name_when_there_is_nothing_to_pin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An allow_unresolved_hostname policy has no address set, so the name is kept.

    This is the documented residual of the pin, not an oversight: refusing to
    send would mean refusing to reach hosts this deployment cannot resolve.
    """

    seen: dict[str, object] = {}

    def fake_getaddrinfo(_host: str, *_args: object, **_kwargs: object) -> object:
        raise socket.gaierror("offline")

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200)

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await safe_async_request(
            client,
            "GET",
            "https://pve.example.invalid:8006/api",
            policy=LAN_INTEGRATION_POLICY,
        )

    assert seen["url"] == "https://pve.example.invalid:8006/api"


def test_pinned_request_does_not_mutate_the_caller_kwargs() -> None:
    """safe_async_request reuses one kwargs dict across redirect hops."""

    validated = validate_outbound_url("https://192.168.1.10:8443/api", LAN_INTEGRATION_POLICY)
    original: dict[str, object] = {"json": {"a": 1}}

    with httpx.Client(trust_env=False) as client:
        target, sent = pinned_request(validated, original, client)

    assert target == "https://192.168.1.10:8443/api"
    assert original == {"json": {"a": 1}}
    assert sent["json"] == {"a": 1}


@pytest.mark.asyncio
async def test_pin_sends_a_punycoded_host_header_for_an_idn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Host header must stay ASCII when the webhook host is an IDN.

    httpx punycodes URL.host on its way to the wire; the pin writes the header
    itself, out of the raw Unicode urlparse() hands back, so without an explicit
    encode the request goes out as b'Host: b\xc3\xbccher.example' -- UTF-8 in a
    field that has to be ASCII.
    """

    raw: dict[str, object] = {}

    def fake_getaddrinfo(_host: str, *_args: object, **_kwargs: object) -> object:
        return _addrinfo("93.184.216.34")

    def handler(request: httpx.Request) -> httpx.Response:
        raw["header"] = dict(request.headers.raw)[b"Host"]
        raw["sni"] = request.extensions.get("sni_hostname")
        return httpx.Response(200)

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await safe_async_request(client, "POST", "https://b\u00fccher.example/hook")

    assert raw["header"] == b"xn--bcher-kva.example"
    assert raw["sni"] == "xn--bcher-kva.example"
