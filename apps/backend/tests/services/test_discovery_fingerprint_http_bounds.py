"""Regression tests for B30 — the two outbound fingerprint probes must be bounded.

``_run_http_fingerprint_probe`` and ``_run_ssdp_unicast_probe`` talk to whatever is
listening on the subnet being scanned, which by definition is not trusted.  Both used
to call ``client.get()`` on a client built with ``follow_redirects=True``, so a hostile
host could (a) hand back a body of any size, which httpx buffered in full before the
caller's ``[:8192]`` slice ever ran, and (b) bounce the probe at a third-party address
of its choosing.

The assertions here are deliberately made against the *transport*, not against the
probe's return value: what is being pinned is how many bytes were pulled off the wire
and which hosts were dialled, and neither of those is visible from the result dict.
"""

from __future__ import annotations

import asyncio
import gzip
import zlib
from collections.abc import AsyncIterator

import httpx
import pytest

from app.services import discovery_fingerprint as fp

# A body big enough that "read it all" and "read the cap" are unmistakably different
# numbers.  Chunks are counted as they leave the generator, so the counter is a direct
# measurement of what the probe pulled, not an inference from the response object.
_CHUNK_BYTES = 4096
_TOTAL_CHUNKS = 4096  # 16 MiB if fully buffered


def _pin_transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:  # type: ignore[no-untyped-def]
    """Force every ``httpx.AsyncClient`` built by the module onto a mock transport.

    The probes construct their own client, so there is no seam to inject through;
    wrapping the class keeps the probe's own client kwargs (timeout, redirect policy)
    exactly as the module sets them, which is the thing under test.
    """
    real_cls = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def _factory(*args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = transport
        return real_cls(*args, **kwargs)

    monkeypatch.setattr(fp.httpx, "AsyncClient", _factory)


def _counting_body(counter: list[int], prefix: bytes = b"") -> AsyncIterator[bytes]:
    async def _gen() -> AsyncIterator[bytes]:
        if prefix:
            counter[0] += 1
            yield prefix
        for _ in range(_TOTAL_CHUNKS):
            counter[0] += 1
            yield b"A" * _CHUNK_BYTES

    return _gen()


# ─────────────────────────────────────────────────────────────────────────────
# _run_http_fingerprint_probe
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_http_probe_does_not_follow_a_cross_host_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dialled: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        dialled.append(request.url.host or "")
        if request.url.host == "192.0.2.10":
            return httpx.Response(
                302, headers={"location": "http://169.254.169.254/latest/meta-data/"}
            )
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<title>x</title>")

    _pin_transport(monkeypatch, handler)

    await fp._run_http_fingerprint_probe("192.0.2.10", [{"port": 80}])

    assert dialled == ["192.0.2.10"], f"probe followed the redirect off-host: {dialled}"


@pytest.mark.asyncio
async def test_http_probe_stops_reading_at_the_body_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    produced = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=_counting_body(produced),
        )

    _pin_transport(monkeypatch, handler)

    await fp._run_http_fingerprint_probe("192.0.2.10", [{"port": 80}])

    # 8 KiB cap over 4 KiB chunks is at most a handful of chunks; a full buffer is
    # _TOTAL_CHUNKS.  The gap between the two is three orders of magnitude.
    assert produced[0] <= 8, f"probe buffered {produced[0] * _CHUNK_BYTES} bytes of body"


# ─────────────────────────────────────────────────────────────────────────────
# _run_ssdp_unicast_probe
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ssdp_probe_does_not_follow_a_cross_host_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dialled: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        dialled.append(request.url.host or "")
        if request.url.host == "192.0.2.10":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/rootDesc.xml"})
        return httpx.Response(
            200,
            headers={"content-type": "text/xml"},
            text="<friendlyName>pwned</friendlyName>",
        )

    _pin_transport(monkeypatch, handler)

    await fp._run_ssdp_unicast_probe("192.0.2.10", [{"port": 80}])

    assert set(dialled) == {"192.0.2.10"}, f"probe followed the redirect off-host: {dialled}"


@pytest.mark.asyncio
async def test_ssdp_probe_stops_reading_at_the_body_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    produced = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/xml"},
            content=_counting_body(produced, prefix=b"<friendlyName>Front Door</friendlyName>"),
        )

    _pin_transport(monkeypatch, handler)

    result = await fp._run_ssdp_unicast_probe("192.0.2.10", [{"port": 80}])

    # The description still parses out of the capped prefix — the cap must not cost
    # the probe its answer for a normally-sized document.
    assert result.get("friendly_name") == "Front Door"
    # 64 KiB cap over 4 KiB chunks, plus the one-chunk prefix.
    assert produced[0] <= 20, f"probe buffered {produced[0] * _CHUNK_BYTES} bytes of body"


# ─────────────────────────────────────────────────────────────────────────────
# Content-Encoding: the body cap has to survive a decompression bomb
#
# The first fix for B30 capped `resp.aiter_bytes()`, which is the *decoded* stream.
# httpx builds its decoder from the response's own Content-Encoding header, so the
# scanned host — the untrusted party — decides whether that decoder runs at all, and
# with chunk_size=None one raw network read becomes one fully-decoded chunk.  The cap
# was therefore tested only after the allocation it exists to prevent: 65 KB of gzip
# on the wire buffered 64 MiB inside the probe, 8192x the declared cap.
#
# These two tests count decompressed bytes at the zlib boundary, which is where the
# allocation actually happens, rather than trusting the length of the string the
# probe returns (that was always short — it is the intermediate buffer that is the
# bug).  Both httpx's GZipDecoder and the module's own bounded decoder go through
# zlib.decompressobj, so the counter sees whichever one runs.
# ─────────────────────────────────────────────────────────────────────────────

# 64 MiB of a single repeated byte compresses to ~65 KB — the classic shape of a
# decompression bomb, and small enough that a hostile host can serve one per probe
# for free.
_BOMB_PLAIN_BYTES = 64 * 1024 * 1024
_GZIP_BOMB = gzip.compress(b"A" * _BOMB_PLAIN_BYTES)
_XML_GZIP_BOMB = gzip.compress(
    b"<friendlyName>Front Door</friendlyName>" + b"A" * _BOMB_PLAIN_BYTES
)


def _streamed(payload: bytes) -> AsyncIterator[bytes]:
    """Serve *payload* as a stream, the way a socket would.

    ``httpx.Response(content=b"...")`` is not a stand-in for a network response: the
    constructor sees a ByteStream and calls ``read()`` on the spot, so the body is
    decoded before the probe is even handed the object and ``aiter_raw`` then raises
    StreamConsumed.  A test written that way measures httpx's constructor and reports
    it as the probe's behaviour.  An async iterator body keeps the response streaming,
    which is the only shape that exercises the code under test.
    """

    async def _gen() -> AsyncIterator[bytes]:
        yield payload

    return _gen()


class _CountingDecompressor:
    """Wraps a real zlib decompressor and tallies the bytes it hands back.

    zlib's Decompress objects are C types and reject attribute assignment, so the
    spy has to be a wrapper rather than a patched method.  __getattr__ forwards
    flush()/eof/unused_data so httpx's own decoder keeps working through it.
    """

    def __init__(self, inner, tally: list[int]) -> None:  # type: ignore[no-untyped-def]
        self._inner = inner
        self._tally = tally

    def decompress(self, data: bytes, max_length: int = 0) -> bytes:
        out = self._inner.decompress(data, max_length)
        self._tally[0] += len(out)
        return out

    def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
        return getattr(self._inner, name)


def _tally_decompressed(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Count every byte produced by any zlib decompressor for the rest of the test."""
    tally = [0]
    real_factory = zlib.decompressobj

    def _factory(*args, **kwargs):  # type: ignore[no-untyped-def]
        return _CountingDecompressor(real_factory(*args, **kwargs), tally)

    monkeypatch.setattr(zlib, "decompressobj", _factory)
    return tally


@pytest.mark.asyncio
async def test_http_probe_body_cap_holds_against_a_gzip_bomb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tally = _tally_decompressed(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        # The host answers with Content-Encoding it was never offered.  That is the
        # whole point: advertising "accept-encoding: identity" is a request, and this
        # peer is under no obligation to honour it.
        return httpx.Response(
            200,
            headers={"content-type": "text/html", "content-encoding": "gzip"},
            content=_streamed(_GZIP_BOMB),
        )

    _pin_transport(monkeypatch, handler)

    await fp._run_http_fingerprint_probe("192.0.2.10", [{"port": 80}])

    assert tally[0] <= 2 * fp._HTTP_MAX_BODY_BYTES, (
        f"probe materialised {tally[0]} decompressed bytes from "
        f"{len(_GZIP_BOMB)} bytes on the wire; cap is {fp._HTTP_MAX_BODY_BYTES}"
    )


@pytest.mark.asyncio
async def test_ssdp_probe_body_cap_holds_against_a_gzip_bomb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tally = _tally_decompressed(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        # A real description document, then 64 MiB of padding, all in one gzip
        # stream.  The prefix means the probe finds its answer on the first path and
        # stops, so the tally below is one response's worth either way — the whole
        # difference between pass and fail is how much of that one response the probe
        # was made to materialise.
        return httpx.Response(
            200,
            headers={"content-type": "text/xml", "content-encoding": "gzip"},
            content=_streamed(_XML_GZIP_BOMB),
        )

    _pin_transport(monkeypatch, handler)

    result = await fp._run_ssdp_unicast_probe("192.0.2.10", [{"port": 80}])

    assert result.get("friendly_name") == "Front Door"
    assert tally[0] <= 2 * fp._UPNP_MAX_BODY_BYTES, (
        f"probe materialised {tally[0]} decompressed bytes from "
        f"{len(_GZIP_BOMB)} bytes on the wire; cap is {fp._UPNP_MAX_BODY_BYTES}"
    )


@pytest.mark.asyncio
async def test_ssdp_probe_still_reads_a_legitimately_gzipped_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guards the bomb fix against over-correcting into "never decompress anything".

    Plenty of embedded HTTP stacks gzip unconditionally.  Refusing to decode would
    turn every one of them into a blank fingerprint, so the cap has to bound the
    decompressor rather than skip it.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/xml", "content-encoding": "gzip"},
            content=_streamed(gzip.compress(b"<friendlyName>Hallway Cam</friendlyName>")),
        )

    _pin_transport(monkeypatch, handler)

    result = await fp._run_ssdp_unicast_probe("192.0.2.10", [{"port": 80}])

    assert result.get("friendly_name") == "Hallway Cam"


@pytest.mark.asyncio
async def test_ssdp_probe_honours_the_declared_charset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cap must not silently downgrade decoding to hard UTF-8.

    Streaming replaced ``resp.text`` — which honours the charset in Content-Type —
    with a fixed utf-8/errors="ignore" decode, so a device that labels its
    description iso-8859-1 (very common on consumer gear) had every non-ASCII byte
    dropped from its friendly name.  That is evidence loss in exactly the device
    classes these probes exist to identify.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/xml; charset=iso-8859-1"},
            content=_streamed("<friendlyName>Küchenkamera</friendlyName>".encode("iso-8859-1")),
        )

    _pin_transport(monkeypatch, handler)

    result = await fp._run_ssdp_unicast_probe("192.0.2.10", [{"port": 80}])

    assert result.get("friendly_name") == "Küchenkamera"


@pytest.mark.asyncio
async def test_ssdp_probe_reuses_one_connection_across_the_upnp_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Skipping a response must not cost the keep-alive connection.

    The probe tries four UPnP description paths per port, and on real gear at least
    three of them 404.  ``client.get()`` used to read those small bodies to
    completion, so httpx returned the connection to the pool and all four requests
    rode one TCP connection.  Streaming and then ``continue``-ing out of the context
    with the body unread forces httpx to close the connection instead, turning one
    handshake per port into four — per port, per host, across a whole subnet sweep.

    The cap still applies to the drain: a skipped response that keeps talking past
    the cap loses its connection, which is the correct outcome for that host.

    This one needs a real socket; MockTransport does not model connections at all.
    """
    connections = [0]

    async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        connections[0] += 1
        try:
            while True:
                request_line = await reader.readline()
                if not request_line:
                    return
                while True:
                    header = await reader.readline()
                    if header in (b"\r\n", b"\n", b""):
                        break
                body = b"nope"
                writer.write(
                    b"HTTP/1.1 404 Not Found\r\n"
                    b"Content-Type: text/plain\r\n"
                    b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                    b"Connection: keep-alive\r\n\r\n" + body
                )
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            return
        finally:
            writer.close()

    server = await asyncio.start_server(_handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setattr(fp, "_UPNP_DESCRIPTION_PORTS", (port,))
    try:
        result = await fp._run_ssdp_unicast_probe("127.0.0.1", [{"port": port}])
    finally:
        server.close()
        await server.wait_closed()

    assert result == {}
    assert connections[0] == 1, (
        f"probe opened {connections[0]} TCP connections for 4 UPnP paths on one port"
    )
