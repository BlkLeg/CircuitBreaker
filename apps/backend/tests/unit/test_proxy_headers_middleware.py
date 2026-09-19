"""The forwarded headers are applied by us, and the socket peer survives it.

`app.middleware.proxy_headers` replaces uvicorn's ProxyHeadersMiddleware. The
replacement exists for one reason: uvicorn overwrote `scope["client"]` with the
X-Forwarded-For address before the app ran, which is the only thing
`core.forwarded` can decide trust on. `request_from_trusted_proxy` therefore
returned False for every request that actually came through nginx, every
forwarded value silently fell back to its default, and the visible symptom was
an agent `server_url` that could not carry a non-443 port — because nginx's
`Host $host` has the port stripped and the X-Forwarded-Host that still had it
was being discarded as untrusted.

These tests hold both halves: the rewrite still happens (audit records must keep
naming the real client), and the peer is still recoverable (trust must keep
working).
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core import forwarded as core_forwarded
from app.middleware.proxy_headers import ProxyHeadersMiddleware


@pytest.fixture(autouse=True)
def _trusted_proxy_is_10_0_0_0_8(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core_forwarded.settings, "trusted_proxy_cidrs", ["10.0.0.0/8"])
    monkeypatch.setattr(core_forwarded, "_trusted_proxy_cache", None)


def _scope(peer: str, scope_type: str = "http", **headers: str) -> dict[str, Any]:
    return {
        "type": scope_type,
        "scheme": "ws" if scope_type == "websocket" else "http",
        "client": (peer, 51234),
        "headers": [(k.replace("_", "-").lower().encode(), v.encode()) for k, v in headers.items()],
    }


async def _run(scope: dict[str, Any]) -> dict[str, Any]:
    """Push `scope` through the middleware and hand back what the app saw."""
    seen: dict[str, Any] = {}

    async def app(inner_scope: dict[str, Any], receive: Any, send: Any) -> None:
        seen.update(inner_scope)

    async def receive() -> dict[str, Any]:  # pragma: no cover - never called
        return {"type": "http.request"}

    async def send(message: dict[str, Any]) -> None:  # pragma: no cover - never called
        return None

    await ProxyHeadersMiddleware(app)(scope, receive, send)
    return seen


# ── the rewrite uvicorn used to do ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_trusted_proxy_sets_the_scheme_the_client_used():
    scope = await _run(_scope("10.0.0.1", x_forwarded_proto="https"))
    assert scope["scheme"] == "https"


@pytest.mark.asyncio
async def test_trusted_proxy_sets_the_client_to_the_real_caller():
    """The dozen `request.client.host` audit call sites depend on this."""
    scope = await _run(_scope("10.0.0.1", x_forwarded_for="203.0.113.5"))
    assert scope["client"] == ("203.0.113.5", 0)


@pytest.mark.asyncio
async def test_a_clients_own_forwarded_for_cannot_name_its_address():
    """nginx *appends*, so a caller's own header survives to the left of its
    real address. Reading left to right would let anyone choose their own
    rate-limit key and rotate identities past the login and MFA limits."""
    scope = await _run(_scope("10.0.0.1", x_forwarded_for="198.51.100.9, 203.0.113.5"))
    assert scope["client"] == ("203.0.113.5", 0)


@pytest.mark.asyncio
async def test_websocket_scope_gets_a_websocket_scheme():
    """A proxy reports the request scheme it saw; a websocket scope's scheme is
    ws/wss. uvicorn made the same translation, and a scope left saying "https"
    makes every absolute URL built off it wrong on the stream endpoints."""
    scope = await _run(_scope("10.0.0.1", scope_type="websocket", x_forwarded_proto="https"))
    assert scope["scheme"] == "wss"


# ── the half uvicorn destroyed ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_socket_peer_survives_the_client_rewrite():
    scope = await _run(_scope("10.0.0.1", x_forwarded_for="203.0.113.5"))
    assert scope["client"] == ("203.0.113.5", 0), "the client must still be rewritten"
    assert core_forwarded.socket_peer(scope) == "10.0.0.1"


@pytest.mark.asyncio
async def test_trust_survives_the_client_rewrite():
    """The regression itself. With uvicorn doing the rewrite this was False,
    which is what silently disabled every forwarded-header consult."""
    scope = await _run(_scope("10.0.0.1", x_forwarded_for="203.0.113.5"))
    assert core_forwarded.request_from_trusted_proxy(scope) is True


@pytest.mark.asyncio
async def test_forwarded_base_url_recovers_a_non_default_port():
    """The bug a user would actually hit: `CB_PORT_HTTPS` is operator-settable,
    nginx sends `Host $host` with the port stripped, and the agent writes this
    URL into agent.toml and dials it with no redirect to follow."""
    scope = await _run(
        _scope(
            "10.0.0.1",
            host="cb.example.com",
            x_forwarded_for="203.0.113.5",
            x_forwarded_proto="https",
            x_forwarded_host="cb.example.com:8443",
        )
    )
    assert core_forwarded.forwarded_base_url(_Conn(scope)) == "https://cb.example.com:8443"


# ── untrusted peers are left alone ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_untrusted_peer_changes_nothing():
    scope = await _run(_scope("203.0.113.5", x_forwarded_proto="https", x_forwarded_for="10.0.0.9"))
    assert scope["scheme"] == "http"
    assert scope["client"] == ("203.0.113.5", 51234)


@pytest.mark.asyncio
async def test_an_untrusted_peer_is_not_promoted_to_trusted():
    """No recorded peer means `socket_peer` falls back to the client, which for
    an untrusted caller is the same address it always was."""
    scope = await _run(_scope("203.0.113.5", x_forwarded_for="10.0.0.9"))
    assert core_forwarded.request_from_trusted_proxy(scope) is False


@pytest.mark.asyncio
async def test_lifespan_scope_passes_straight_through():
    seen: dict[str, Any] = {}

    async def app(inner_scope: dict[str, Any], receive: Any, send: Any) -> None:
        seen.update(inner_scope)

    async def noop() -> None:  # pragma: no cover - never called
        return None

    await ProxyHeadersMiddleware(app)({"type": "lifespan"}, noop, noop)
    assert seen == {"type": "lifespan"}


class _Conn:
    """A Request-shaped view of a raw scope, which is what `core.forwarded`'s
    public helpers take."""

    def __init__(self, scope: dict[str, Any]) -> None:
        self.scope = scope
        self.headers = {k.decode(): v.decode() for k, v in scope.get("headers", ())}
        client = scope.get("client") or ("", 0)

        class _Client:
            host = client[0]

        class _Url:
            scheme = scope.get("scheme", "http")
            netloc = ""

        self.client = _Client()
        self.url = _Url()
