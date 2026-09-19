"""Apply `X-Forwarded-*` from our own reverse proxy, preserving the socket peer.

This replaces uvicorn's `ProxyHeadersMiddleware`, which every launch path now
disables with `--no-proxy-headers` (`proxy_headers=False` for
`start.py`'s `uvicorn.run`). It is not a reimplementation for its own sake —
uvicorn's version destroys the one fact `app.core.forwarded` needs.

uvicorn rewrites `scope["client"]` to the address it reads out of
`X-Forwarded-For` before the application is ever called. By the time
`core.forwarded.request_from_trusted_proxy` looks at the peer, it is therefore
the *end client*, not our proxy, so the check returns False on every request
that actually came through nginx. Every forwarded value then silently fell back
to its default:

* `forwarded_host` returned the `Host` header, and nginx's `Host $host` has the
  port stripped — so `forwarded_base_url` could not recover a non-default port
  and wrote `https://cb.example.com` into every agent's `agent.toml` for a
  server reachable only at `https://cb.example.com:8443`. `CB_PORT_HTTPS` is
  operator-settable, so every install not on 443 shipped an unreachable
  `server_url`, and an agent dials it directly with no redirect to follow.
* The module's documented threat model — "a peer that is not one of our own
  proxies cannot steer the URL" — described a check that was not running.

Simply passing `--no-proxy-headers` without this middleware is not an option:
roughly a dozen call sites read `request.client.host` for audit and security
records (`core/audit.py`, `middleware/csrf.py`, `api/auth.py`'s MFA failures,
`services/auth_service.py`), and all of them would have started recording
127.0.0.1 as the client for every audited action.

So this does exactly what uvicorn's did — set the scheme and the client from
the forwarded headers, only when the socket peer is one of ours — and
additionally records the original peer under `SOCKET_PEER_SCOPE_KEY`, which is
what `core.forwarded` consults for its trust decision. One knob decides trust
now (`CB_TRUSTED_PROXY_CIDRS`) instead of that setting and uvicorn's
independent `--forwarded-allow-ips` disagreeing silently.

Registered last in `main.py` so it is the true outermost layer: everything that
reads `request.client` must run inside it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.forwarded import SOCKET_PEER_SCOPE_KEY, forwarded_client_identity, is_trusted_peer

if TYPE_CHECKING:  # pragma: no cover - typing only
    from starlette.types import ASGIApp, Receive, Scope, Send

#: Only these two scope types carry a peer, headers and a scheme. Anything else
#: (the lifespan scope) is passed straight through untouched.
_HANDLED_SCOPE_TYPES = frozenset({"http", "websocket"})


def _header(scope: Scope, name: str) -> str:
    """Read one header out of a raw ASGI scope, lower-cased name, "" if absent."""
    target = name.encode("latin-1")
    for key, value in scope.get("headers", ()):
        if key.lower() == target:
            return str(value.decode("latin-1"))
    return ""


def _peer_host(scope: Scope) -> str:
    """The socket peer's address as a string ("" when the server reports none)."""
    client = scope.get("client")
    if isinstance(client, (list, tuple)) and client:
        return str(client[0])
    return ""


def _scheme_for(scope_type: str, forwarded_proto: str) -> str:
    """Map a forwarded `http`/`https` onto the scheme this scope type uses.

    A websocket scope's scheme is `ws`/`wss`, never `http`/`https`, and a proxy
    reports the *request* scheme it saw. uvicorn made the same translation; a
    websocket scope left saying `https` would make `request.url_for` and any
    absolute URL built off the scope wrong in a way that only shows up on the
    stream endpoints.
    """
    if scope_type == "websocket":
        return "wss" if forwarded_proto == "https" else "ws"
    return forwarded_proto


class ProxyHeadersMiddleware:
    """Pure-ASGI, so websocket scopes get the same treatment as HTTP ones.

    `BaseHTTPMiddleware` would not do: the agent enroll and link endpoints are
    websockets, and `api/ws_agents.py` reads `websocket.client.host` for its
    per-IP limits. A middleware that silently skipped websocket scopes would
    leave those reading the proxy's address for every agent in the fleet.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in _HANDLED_SCOPE_TYPES:
            await self.app(scope, receive, send)
            return

        peer = _peer_host(scope)
        if not is_trusted_peer(peer):
            # Not one of our proxies. Its forwarded headers are unverifiable
            # claims, so nothing is applied and the scope keeps describing the
            # connection the server actually accepted.
            await self.app(scope, receive, send)
            return

        # Recorded before `client` is overwritten — this is the whole reason
        # this middleware exists rather than uvicorn's.
        scope[SOCKET_PEER_SCOPE_KEY] = peer

        forwarded_proto = _header(scope, "x-forwarded-proto").split(",")[0].strip().lower()
        if forwarded_proto in ("http", "https"):
            scope["scheme"] = _scheme_for(scope["type"], forwarded_proto)

        # The same rightmost-untrusted-hop walk the rate limiter uses, not the
        # leftmost entry: nginx *appends* to X-Forwarded-For, so a client's own
        # header survives to the left of its real address and reading left to
        # right would let any caller name its own address.
        client = forwarded_client_identity(_ForwardedHeaders(scope))
        if client:
            # Port 0: the forwarded header carries an address, never the peer
            # port, and uvicorn recorded it the same way.
            scope["client"] = (client, 0)

        await self.app(scope, receive, send)


class _ForwardedHeaders:
    """Adapts a raw ASGI scope to the `.get(name)` shape `forwarded_client_identity`
    expects, so the hop-walking rule has one implementation rather than a
    scope-flavoured copy of it."""

    def __init__(self, scope: Scope) -> None:
        self._scope = scope

    def get(self, name: str, default: str = "") -> str:
        return _header(self._scope, name.lower()) or default
