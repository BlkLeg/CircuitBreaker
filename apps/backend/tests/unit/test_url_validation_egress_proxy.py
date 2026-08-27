"""The address pin against real sockets: a forward proxy, TLS, and the pool.

`pinned_request` rewrites a validated URL to the IP literal that validation
approved and carries the name in `Host` and in the `sni_hostname` extension.
Three things about that are only true on the wire, so they are tested on the
wire rather than by reading httpcore:

* httpcore honours `sni_hostname` on a direct connection, so the certificate is
  still checked against the name (this was shipped unverified).
* it does **not** honour it on the CONNECT path -- `AsyncTunnelHTTPConnection`
  builds `server_hostname` from the request URL's host -- so an unconditional
  pin fails certificate verification for every HTTPS request whenever an egress
  proxy is configured, which is the deployment docs/deployment-security.md
  tells operators to run. The pin is skipped there.
* httpcore keys its connection pool on origin and leaves `sni_hostname` out of
  the key, so pinning two names onto one address would let the second reuse a
  connection whose certificate was validated only for the first.

Maintainers: if you make the pin unconditional again, or drop `sni_hostname`,
or let the feed client keep connections alive, this file fails.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import socket
import ssl
from pathlib import Path

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.core.url_validation import (
    MONITOR_TARGET_POLICY,
    pinned_request,
    safe_async_request,
    validate_outbound_url,
)

_HOSTNAME = "webhook.example"
_PUBLIC_ADDRESS = "93.184.216.34"

_REAL_GETADDRINFO = socket.getaddrinfo


def _fake_dns(monkeypatch: pytest.MonkeyPatch, answers: dict[str, str]) -> None:
    """Answer for the named hosts; leave every other lookup real.

    The loopback connections these tests make (client -> proxy, proxy -> origin)
    go through getaddrinfo too, so the fake has to delegate rather than answer
    everything.
    """

    def fake_getaddrinfo(host: str, *args: object, **kwargs: object) -> object:
        address = answers.get(host)
        if address is None:
            return _REAL_GETADDRINFO(host, *args, **kwargs)  # type: ignore[arg-type]
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 443))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


def _write_cert(tmp_path: Path, *names: str) -> tuple[Path, Path]:
    """A self-signed certificate for *names*, used as its own CA."""

    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0])])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(name) for name in names]), critical=False
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    stem = names[0].replace(".", "_")
    cert_path = tmp_path / f"{stem}.pem"
    key_path = tmp_path / f"{stem}.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


class _Origin:
    """A keep-alive HTTP/1.1 server, optionally over TLS, that counts connections.

    Keep-alive is not incidental: a server that hung up after each response
    would force a fresh connection on its own and hide whether the client's pool
    reused one.
    """

    def __init__(self, bodies: dict[str, bytes] | None = None) -> None:
        self.bodies = bodies or {}
        self.connections = 0
        self.host_headers: list[str] = []
        self.server: asyncio.AbstractServer | None = None
        self.port = 0

    async def start(self, ssl_context: ssl.SSLContext | None = None) -> None:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0, ssl=ssl_context)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        try:
            while head := await reader.readuntil(b"\r\n\r\n"):
                host = ""
                for line in head.decode("latin-1").split("\r\n")[1:]:
                    if line.lower().startswith("host:"):
                        host = line.split(":", 1)[1].strip()
                self.host_headers.append(host)
                body = self.bodies.get(host.split(":")[0], b"")
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, ssl.SSLError):
            pass
        finally:
            writer.close()


async def _start_connect_proxy(
    origin_port: int, seen: list[str]
) -> tuple[asyncio.AbstractServer, int]:
    """A CONNECT proxy that records the authority and tunnels to the origin.

    It ignores the requested authority and always relays to the local origin, so
    the only thing deciding whether the handshake succeeds is the server_hostname
    the client chose -- which httpcore derives from that same authority.
    """

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, ConnectionError):
            writer.close()
            return
        request_line = head.split(b"\r\n", 1)[0].decode("latin-1")
        parts = request_line.split(" ")
        seen.append(parts[1] if len(parts) > 1 else request_line)
        if parts[0] != "CONNECT":
            writer.write(b"HTTP/1.1 405 Method Not Allowed\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            writer.close()
            return
        writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        await writer.drain()

        up_reader, up_writer = await asyncio.open_connection("127.0.0.1", origin_port)

        async def pump(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
            try:
                while chunk := await src.read(65536):
                    dst.write(chunk)
                    await dst.drain()
            except (ConnectionError, asyncio.CancelledError):
                pass
            finally:
                dst.close()

        await asyncio.gather(
            pump(reader, up_writer), pump(up_reader, writer), return_exceptions=True
        )

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


def _server_context(cert_path: Path, key_path: Path) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert_path), str(key_path))
    return context


@pytest.mark.asyncio
async def test_https_webhook_still_completes_through_a_connect_proxy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A pinned URL makes the proxy tunnel to an IP, and TLS then rejects it."""

    cert_path, key_path = _write_cert(tmp_path, _HOSTNAME)
    origin = _Origin({_HOSTNAME: b""})
    await origin.start(_server_context(cert_path, key_path))
    authorities: list[str] = []
    proxy, proxy_port = await _start_connect_proxy(origin.port, authorities)
    _fake_dns(monkeypatch, {_HOSTNAME: _PUBLIC_ADDRESS})

    verify = ssl.create_default_context(cafile=str(cert_path))
    try:
        async with httpx.AsyncClient(
            proxy=f"http://127.0.0.1:{proxy_port}",
            trust_env=False,
            verify=verify,
            timeout=10.0,
        ) as client:
            response = await asyncio.wait_for(
                safe_async_request(client, "POST", f"https://{_HOSTNAME}/hook", json={"a": 1}),
                timeout=20,
            )
    finally:
        proxy.close()
        await proxy.wait_closed()
        await origin.stop()

    assert response.status_code == 200
    # The proxy was asked to tunnel to the *name*. Had it been asked for
    # 93.184.216.34:443, httpcore would have handshaked with
    # server_hostname='93.184.216.34' and the request above would have raised
    # SSLCertVerificationError before reaching this line.
    assert authorities == [f"{_HOSTNAME}:443"]


@pytest.mark.asyncio
async def test_direct_pin_completes_a_real_tls_handshake_against_the_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """On a direct connection the pin's sni_hostname really does drive the handshake.

    The pin shipped on the strength of reading httpcore, with "unverified
    against a real TLS handshake" filed as a residual. This dials a real TLS
    server holding a certificate for the *name* while the URL says the address:
    it can only succeed if httpcore passed sni_hostname through as
    server_hostname, and it fails with "IP address mismatch" if anyone drops
    that extension. MONITOR_TARGET_POLICY is used only because it is the one
    policy that permits a loopback answer, which is where a test can host a
    server.
    """

    cert_path, key_path = _write_cert(tmp_path, _HOSTNAME)
    origin = _Origin({_HOSTNAME: b""})
    await origin.start(_server_context(cert_path, key_path))
    _fake_dns(monkeypatch, {_HOSTNAME: "127.0.0.1"})

    verify = ssl.create_default_context(cafile=str(cert_path))
    try:
        async with httpx.AsyncClient(trust_env=False, verify=verify, timeout=10.0) as client:
            response = await asyncio.wait_for(
                safe_async_request(
                    client,
                    "GET",
                    f"https://{_HOSTNAME}:{origin.port}/hook",
                    policy=MONITOR_TARGET_POLICY,
                ),
                timeout=20,
            )
    finally:
        await origin.stop()

    assert response.status_code == 200
    assert str(response.request.url) == f"https://127.0.0.1:{origin.port}/hook"
    assert origin.host_headers == [f"{_HOSTNAME}:{origin.port}"]


@pytest.mark.asyncio
async def test_pin_is_skipped_for_an_explicitly_proxied_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_dns(monkeypatch, {_HOSTNAME: _PUBLIC_ADDRESS})
    validated = validate_outbound_url(f"https://{_HOSTNAME}/hook")

    async with httpx.AsyncClient(proxy="http://127.0.0.1:3128", trust_env=False) as proxied:
        target, sent = pinned_request(validated, {"json": {"a": 1}}, proxied)
    assert target == f"https://{_HOSTNAME}/hook"
    # Nothing is added either: the proxied path must behave exactly as it did
    # before the pin existed, headers and extensions included.
    assert sent == {"json": {"a": 1}}

    async with httpx.AsyncClient(trust_env=False) as direct:
        target, sent = pinned_request(validated, {"json": {"a": 1}}, direct)
    assert target == f"https://{_PUBLIC_ADDRESS}:443/hook"
    assert sent["headers"]["host"] == _HOSTNAME


@pytest.mark.asyncio
async def test_pin_is_skipped_for_a_proxy_that_came_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CB_EGRESS_PROXY_URL is not the only way a proxy gets in front of a request.

    `outbound_async_client` leaves `trust_env` at its default when no egress
    proxy is configured, so HTTPS_PROXY in the container environment still
    routes every webhook through a CONNECT tunnel. Deciding the pin from the
    setting alone would leave that deployment broken.
    """

    _fake_dns(monkeypatch, {_HOSTNAME: _PUBLIC_ADDRESS})
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:3128")
    validated = validate_outbound_url(f"https://{_HOSTNAME}/hook")

    async with httpx.AsyncClient() as client:
        target, sent = pinned_request(validated, {}, client)

    assert target == f"https://{_HOSTNAME}/hook"
    assert sent == {}


@pytest.mark.asyncio
async def test_pin_still_applies_to_a_host_the_proxy_settings_exclude(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NO_PROXY means this request dials directly, so the pin must stay on."""

    _fake_dns(monkeypatch, {_HOSTNAME: _PUBLIC_ADDRESS})
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:3128")
    monkeypatch.setenv("NO_PROXY", _HOSTNAME)
    validated = validate_outbound_url(f"https://{_HOSTNAME}/hook")

    async with httpx.AsyncClient() as client:
        target, sent = pinned_request(validated, {}, client)

    assert target == f"https://{_PUBLIC_ADDRESS}:443/hook"
    assert sent["extensions"]["sni_hostname"] == _HOSTNAME


class _ResolvingTransport(httpx.AsyncBaseTransport):
    """Resolves the request host the way a real connection pool would.

    httpx hands the URL's host to the pool, which resolves it again at connect
    time. This stand-in reproduces that second lookup so a test can see which
    address the request would truly have been dialed at.
    """

    def __init__(self, body: bytes = b"") -> None:
        self.dialed: list[str] = []
        self.hosts: list[str | None] = []
        self._body = body

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        self.hosts.append(request.headers.get("host"))
        try:
            socket.inet_pton(socket.AF_INET6 if ":" in host else socket.AF_INET, host)
        except OSError:
            infos = socket.getaddrinfo(host, request.url.port or 443, type=socket.SOCK_STREAM)
            self.dialed.append(str(infos[0][4][0]))
        else:
            self.dialed.append(host)
        return httpx.Response(200, content=self._body, request=request)


@pytest.mark.asyncio
async def test_threat_feed_download_is_dialed_at_the_validated_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B27's second site: the feed download resolved twice and dialed the second answer."""

    from app.services.threat_feed import PublicBlocklistProvider

    answers = iter([_PUBLIC_ADDRESS, "127.0.0.1"])

    def rebinding_getaddrinfo(host: str, *args: object, **kwargs: object) -> object:
        if host != "feed.example":
            return _REAL_GETADDRINFO(host, *args, **kwargs)  # type: ignore[arg-type]
        address = next(answers, "127.0.0.1")
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 443))]

    monkeypatch.setattr(socket, "getaddrinfo", rebinding_getaddrinfo)

    transport = _ResolvingTransport(b"blocked.example\n")
    async with httpx.AsyncClient(transport=transport) as client:
        body = await PublicBlocklistProvider._download_capped(client, "https://feed.example/list")

    assert body == "blocked.example\n"
    assert transport.dialed == [_PUBLIC_ADDRESS]
    assert transport.hosts == ["feed.example"]


@pytest.mark.asyncio
async def test_feed_client_does_not_reuse_a_connection_across_two_feed_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Pinning makes the pool key an address, so two names must not share a socket.

    httpcore keys connections on origin and does not include sni_hostname in the
    key. Once both feed names are rewritten to the same IP:port they are the
    same origin, and a pooled connection validated for feed-a would carry
    feed-b's request with no certificate check of its own. The feed client
    therefore keeps nothing alive. Here the certificate names only feed-a: the
    second download must fail, and it fails only because it opened its own
    connection and did its own handshake.
    """

    from app.services import threat_feed

    good, other = "feed-a.example", "feed-b.example"
    cert_path, key_path = _write_cert(tmp_path, good)
    origin = _Origin({good: b"blocked-a.example\n", other: b"blocked-b.example\n"})
    await origin.start(_server_context(cert_path, key_path))
    _fake_dns(monkeypatch, {good: "127.0.0.1", other: "127.0.0.1"})
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(var, raising=False)

    # The feed policy refuses loopback, which is the only address a test can
    # serve from; swap in a policy that allows it and change nothing else.
    monkeypatch.setattr(
        threat_feed,
        "THREAT_FEED_POLICY",
        type(threat_feed.THREAT_FEED_POLICY)(
            name="Feed URL",
            allowed_schemes=frozenset({"https"}),
            allow_local=True,
        ),
    )
    verify = ssl.create_default_context(cafile=str(cert_path))
    real_factory = threat_feed.outbound_async_client
    monkeypatch.setattr(
        threat_feed,
        "outbound_async_client",
        lambda **kwargs: real_factory(verify=verify, **kwargs),
    )

    provider = threat_feed.PublicBlocklistProvider(
        urls={
            "malware": [
                f"https://{good}:{origin.port}/list",
                f"https://{other}:{origin.port}/list",
            ],
            "trackers": [],
            "botnets": [],
        }
    )
    try:
        with caplog.at_level(logging.WARNING, logger="app.services.threat_feed"):
            feed = await asyncio.wait_for(provider.fetch(), timeout=20)
    finally:
        await origin.stop()

    # If the pool had reused feed-a's connection, feed-b would have been served
    # over it with no handshake of its own and its domain would be in the set.
    assert feed.malware == {"blocked-a.example"}, (
        "feed-b was served over a connection whose certificate was verified for "
        "feed-a — the pin collapsed two names onto one origin and the pool "
        "carried the second across"
    )
    # ...and it has to have failed for the RIGHT reason. A connection error, a
    # timeout or a parse failure would satisfy the assertion above while proving
    # nothing about certificate identity. Only a hostname mismatch shows feed-b
    # opened its own connection and ran its own handshake against a certificate
    # that does not name it.
    mismatch = [
        r.getMessage()
        for r in caplog.records
        if "feed-b.example" in r.getMessage() and "Hostname mismatch" in r.getMessage()
    ]
    assert mismatch, (
        "feed-b did not fail with a certificate hostname mismatch, so this test "
        "is not showing that it did its own handshake:\n"
        + "\n".join(r.getMessage() for r in caplog.records)
    )
    # The server only counts connections that completed a TLS handshake, so
    # feed-b's rejected attempt is deliberately not counted here.
    assert origin.connections == 1
