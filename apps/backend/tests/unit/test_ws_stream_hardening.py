"""What the WebSocket streams believe about their peer, and how much state one
connection may make the server hold.

Three defects are pinned here, all of which fail against the pre-fix handlers:

* B24 — all five streams (`/ws/discovery`, telemetry, monitors, topology,
  agents) derived the connection's identity from the *leftmost*
  `X-Forwarded-For` entry, read off any peer. The shipped nginx appends
  (`$proxy_add_x_forwarded_for`), so the leftmost entry is whatever the client
  typed. That made the per-IP connection cap and — on telemetry *and* monitors —
  the `ws_allowed_cidrs` network allowlist selectable by the caller: rotate the
  header to get a fresh cap bucket, or name an address inside the allowlist to
  walk through it. app/core/forwarded.py already owns this trust decision for
  the rate limiter and the security headers; all five handlers now reach it
  through the single shared `ws_discovery.trusted_ws_client_ip`.

  The parametrization over all five modules is the point of these tests, not
  thoroughness for its own sake: the first attempt at B24 fixed two of the five
  copies and left the /ws/monitors allowlist bypass live. A new stream that
  grows its own `_extract_client_ip` must be added to `_IP_MODULES`.

* B25 — the telemetry stream capped how many channels a *single* subscribe
  frame could name, but merged every frame into one accumulating set with no
  aggregate limit, so a client could hold an unbounded channel set on one
  authenticated socket; and it tore down and rebuilt the whole Redis pubsub on
  every subscribe frame, including frames that asked for nothing new, so a
  client could bill the server an O(n) resubscribe per frame for free.

* The telemetry per-IP tally could be wiped by a double `_unregister` for one
  socket, which the error path performs, freeing every other connection from
  that address from `_MAX_PER_IP`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.api import ws_agents, ws_discovery, ws_monitors, ws_telemetry, ws_topology
from app.core import forwarded as core_forwarded


class _Headers(dict):
    """Case-insensitive header mapping, like Starlette's."""

    def get(self, key, default=None):
        return super().get(key.lower(), default)


class _FakeWebSocket:
    """Records what a handler sent and how it closed; replays scripted frames."""

    def __init__(self, peer: str | None = None, frames: list[str] | None = None, **headers):
        self.client = SimpleNamespace(host=peer) if peer else None
        self.headers = _Headers({k.replace("_", "-").lower(): v for k, v in headers.items()})
        self.scope = {
            "type": "websocket",
            "scheme": "wss",
            "client": (peer, 51234) if peer else None,
            "headers": [],
        }
        self._frames = list(frames or [])
        self.sent: list[str] = []
        self.close_code: int | None = None
        self.accepted = False
        self.application_state = WebSocketState.CONNECTED

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, text: str) -> None:
        self.sent.append(text)

    async def close(self, code: int = 1000) -> None:
        self.close_code = code

    async def receive_text(self) -> str:
        if not self._frames:
            raise WebSocketDisconnect(1000)
        await asyncio.sleep(0)
        return self._frames.pop(0)

    # ── assertions helpers ──────────────────────────────────────────────
    def errors(self) -> list[str]:
        out = []
        for raw in self.sent:
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if isinstance(msg, dict) and "error" in msg:
                out.append(msg["error"])
        return out


@pytest.fixture(autouse=True)
def _trusted_proxy_is_10_0_0_0_8(monkeypatch):
    monkeypatch.setattr(core_forwarded.settings, "trusted_proxy_cidrs", ["10.0.0.0/8"])
    monkeypatch.setattr(core_forwarded, "_trusted_proxy_cache", None)


# Every WS handler that keys a security decision on the client address. B24 was
# filed against all five; only two were fixed on the first pass.
_IP_MODULES = [ws_discovery, ws_telemetry, ws_monitors, ws_topology, ws_agents]
_IP_IDS = [m.__name__.rsplit(".", 1)[-1] for m in _IP_MODULES]


# ── B24: the cap/allowlist key may not be chosen by the client ───────────────


@pytest.mark.parametrize("module", _IP_MODULES, ids=_IP_IDS)
def test_forged_forwarded_from_an_untrusted_peer_does_not_change_the_key(module):
    """Two handshakes from one peer, two forged headers — one cap bucket."""
    first = module._extract_client_ip(_FakeWebSocket("203.0.113.5", x_forwarded_for="1.2.3.4"))
    second = module._extract_client_ip(_FakeWebSocket("203.0.113.5", x_forwarded_for="5.6.7.8"))
    assert first == second == "203.0.113.5"


@pytest.mark.parametrize("module", _IP_MODULES, ids=_IP_IDS)
def test_trusted_proxy_chain_yields_the_hop_the_client_could_not_write(module):
    """nginx appends the real peer, so the rightmost untrusted hop is the client."""
    ws = _FakeWebSocket("10.0.0.1", x_forwarded_for="1.2.3.4, 203.0.113.7")
    assert module._extract_client_ip(ws) == "203.0.113.7"


@pytest.mark.parametrize("module", _IP_MODULES, ids=_IP_IDS)
def test_socket_peer_is_used_when_no_forwarded_header_is_present(module):
    assert module._extract_client_ip(_FakeWebSocket("198.51.100.4")) == "198.51.100.4"


@pytest.mark.parametrize("module", _IP_MODULES, ids=_IP_IDS)
def test_unknown_when_there_is_no_peer_at_all(module):
    assert module._extract_client_ip(_FakeWebSocket(None)) == "unknown"


# ── Telemetry handler harness (auth stubbed; the ACL under test is real) ─────


@pytest.fixture
def telemetry_handler(monkeypatch):
    """Drive telemetry_stream with real ACL/subscription logic and stub auth."""

    def _install(*, ws_allowed_cidrs: str = "[]"):
        @contextlib.contextmanager
        def _session():
            yield SimpleNamespace(
                get=lambda model, pk: SimpleNamespace(
                    is_active=True, locked_until=None, role="admin", demo_expires=None
                )
            )

        async def _no_redis():
            return None

        monkeypatch.setattr(ws_telemetry, "ws_require_wss", lambda: False)
        monkeypatch.setattr(ws_telemetry, "token_from_websocket_scope", lambda scope: "tok")
        monkeypatch.setattr(ws_telemetry, "_db_session", SimpleNamespace(SessionLocal=_session))
        monkeypatch.setattr(
            ws_telemetry,
            "get_or_create_settings",
            lambda db: SimpleNamespace(jwt_secret="secret", ws_allowed_cidrs=ws_allowed_cidrs),
        )
        # Auth is stubbed so this fixture can isolate the forwarded-header and
        # CIDR logic it exists to test. It patches the one seam the stream now
        # uses — `resolve_ws_session_user` (F10 consolidation) — rather than the
        # `is_session_revoked` + `decode_token` pair the inlined handshake used
        # to call directly.
        monkeypatch.setattr(
            ws_telemetry, "resolve_ws_session_user", lambda db, tok: SimpleNamespace(id=1)
        )
        monkeypatch.setattr(ws_telemetry, "get_redis", _no_redis)

    ws_telemetry._connections.clear()
    ws_telemetry._ip_counts.clear()
    yield _install
    ws_telemetry._connections.clear()
    ws_telemetry._ip_counts.clear()


async def test_forged_forwarded_cannot_walk_through_the_cidr_allowlist(telemetry_handler):
    """An off-net caller naming an allowlisted address must still be rejected."""
    telemetry_handler(ws_allowed_cidrs='["10.0.0.0/8"]')
    ws = _FakeWebSocket("203.0.113.5", x_forwarded_for="10.0.0.7")

    await asyncio.wait_for(ws_telemetry.telemetry_stream(ws), timeout=5)

    assert "ip_not_allowed" in ws.errors()
    assert ws.close_code == 1008


# ── B24 on /ws/monitors: the forged value also faced a network ACL ───────────


@pytest.fixture
def monitor_handler(monkeypatch):
    """Drive monitor_stream with the real CIDR allowlist gate and stub auth."""

    def _install(*, ws_allowed_cidrs: str = "[]"):
        @contextlib.contextmanager
        def _session():
            yield SimpleNamespace()

        async def _no_redis():
            return None

        monkeypatch.setattr(ws_monitors, "ws_require_wss", lambda: False)
        monkeypatch.setattr(ws_monitors, "token_from_websocket_scope", lambda scope: "tok")
        monkeypatch.setattr(ws_monitors, "_db_session", SimpleNamespace(SessionLocal=_session))
        monkeypatch.setattr(
            ws_monitors,
            "_authenticate_monitor_reader",
            lambda db, tok: SimpleNamespace(id=1, role="admin"),
        )
        monkeypatch.setattr(
            ws_monitors,
            "get_or_create_settings",
            lambda db: SimpleNamespace(ws_allowed_cidrs=ws_allowed_cidrs),
        )
        monkeypatch.setattr(ws_monitors, "get_redis", _no_redis)

    ws_monitors._connections.clear()
    ws_monitors._ip_counts.clear()
    yield _install
    ws_monitors._connections.clear()
    ws_monitors._ip_counts.clear()


async def test_forged_forwarded_cannot_walk_through_the_monitor_cidr_allowlist(monitor_handler):
    """An off-net caller naming an allowlisted address must still be rejected.

    This is the severe half of B24 and the half the first fix pass missed: the
    monitor stream matches `ws_allowed_cidrs` against the same client address the
    telemetry stream does, so an unpatched `_extract_client_ip` here is a network
    ACL an off-net client passes by writing one header.
    """
    monitor_handler(ws_allowed_cidrs='["10.0.0.0/8"]')
    ws = _FakeWebSocket("203.0.113.5", x_forwarded_for="10.0.0.7")

    await asyncio.wait_for(ws_monitors.monitor_stream(ws), timeout=5)

    assert "ip_not_allowed" in ws.errors()
    assert ws.close_code == 1008


async def test_a_genuinely_allowlisted_monitor_client_still_gets_in(monitor_handler):
    """Negative control: the gate above rejects on the address, not on principle."""
    monitor_handler(ws_allowed_cidrs='["10.0.0.0/8"]')
    ws = _FakeWebSocket("10.0.0.9")

    await asyncio.wait_for(ws_monitors.monitor_stream(ws), timeout=5)

    assert "ip_not_allowed" not in ws.errors()
    assert '{"status": "connected"}' in ws.sent


# ── B25: the accumulated channel set is capped, not just each frame ──────────


def _subscribe(start: int, count: int) -> str:
    return json.dumps({"subscribe": list(range(start, start + count))})


async def test_repeated_subscribe_frames_cannot_grow_the_channel_set_without_bound(
    telemetry_handler,
):
    """Each frame is under the per-frame cap; together they blow past the total."""
    telemetry_handler()
    cap = ws_telemetry._MAX_SUBSCRIPTIONS
    frames = [_subscribe(0, cap), _subscribe(cap, cap), _subscribe(cap * 2, cap)]
    ws = _FakeWebSocket("198.51.100.4", frames=frames)

    await asyncio.wait_for(ws_telemetry.telemetry_stream(ws), timeout=10)

    assert "subscription_limit_exceeded" in ws.errors()
    assert ws.close_code == 1008
    # The overflowing frame must not have been left to run the rest of the loop.
    assert ws._frames, "handler kept reading frames after the cap was exceeded"


async def test_resubscribing_the_same_channels_is_not_an_overflow(telemetry_handler):
    """The cap counts distinct channels, so an idempotent client is unaffected."""
    telemetry_handler()
    cap = ws_telemetry._MAX_SUBSCRIPTIONS
    frames = [_subscribe(0, cap), _subscribe(0, cap), _subscribe(0, cap)]
    ws = _FakeWebSocket("198.51.100.4", frames=frames)

    await asyncio.wait_for(ws_telemetry.telemetry_stream(ws), timeout=10)

    assert ws.errors() == []
    assert ws.close_code is None


async def test_identical_subscribe_frames_do_not_rebuild_the_redis_subscription(
    telemetry_handler, monkeypatch
):
    """B25's other half: a no-op subscribe frame must not cost an O(n) resubscribe.

    Capping the accumulated set stops it growing, but it does not stop a client
    from resending the same ids forever: each frame used to cancel the listener,
    UNSUBSCRIBE every channel, close the pubsub and issue a fresh N-channel
    SUBSCRIBE, at no cost to the sender, for a subscription set that did not
    change. Count listener constructions, not executions — a task cancelled
    before its first step never runs its body, so a body-side counter would
    silently under-count the churn this pins.
    """
    telemetry_handler()
    built: list[frozenset[str]] = []

    def _fake_listener(ws, channels, stop_event):
        built.append(frozenset(channels))

        async def _run():
            await stop_event.wait()

        return _run()

    monkeypatch.setattr(ws_telemetry, "_redis_listener", _fake_listener)
    frames = [_subscribe(0, 5), _subscribe(0, 5), _subscribe(0, 5)]
    ws = _FakeWebSocket("198.51.100.4", frames=frames)

    await asyncio.wait_for(ws_telemetry.telemetry_stream(ws), timeout=10)

    assert ws.errors() == []
    assert len(built) == 1, f"resubscribed {len(built)}x for 3 identical frames"
    assert built[0] == {f"telemetry:{i}" for i in range(5)}


async def test_a_frame_that_adds_a_channel_still_rebuilds(telemetry_handler, monkeypatch):
    """Negative control: the skip above is keyed on 'nothing new', not on 'subscribe'."""
    telemetry_handler()
    built: list[frozenset[str]] = []

    def _fake_listener(ws, channels, stop_event):
        built.append(frozenset(channels))

        async def _run():
            await stop_event.wait()

        return _run()

    monkeypatch.setattr(ws_telemetry, "_redis_listener", _fake_listener)
    frames = [_subscribe(0, 5), _subscribe(5, 1)]
    ws = _FakeWebSocket("198.51.100.4", frames=frames)

    await asyncio.wait_for(ws_telemetry.telemetry_stream(ws), timeout=10)

    assert len(built) == 2
    assert built[-1] == {f"telemetry:{i}" for i in range(6)}


@pytest.mark.parametrize("module", [ws_telemetry, ws_monitors], ids=["telemetry", "monitors"])
async def test_double_unregister_does_not_free_the_other_connections_from_that_ip(module):
    """The handler's error path unregisters a socket the finally already unregistered.

    The old body decremented unconditionally and treated a count of 0 as `<= 1`,
    so the second call popped the IP key and every other live connection from
    that address stopped counting against `_MAX_PER_IP`. Both streams carry the
    same registry, so both are pinned here — leaving the second copy for later
    is how B24 got shipped half-fixed.
    """
    module._connections.clear()
    module._ip_counts.clear()
    ip = "203.0.113.9"
    first = _FakeWebSocket(ip)
    second = _FakeWebSocket(ip)

    await module._register(first, ip)
    await module._register(second, ip)
    assert module._ip_counts[ip] == 2

    await module._unregister(first, ip)
    await module._unregister(first, ip)

    assert module._ip_counts.get(ip) == 1, "second unregister wiped the tally"

    module._connections.clear()
    module._ip_counts.clear()
