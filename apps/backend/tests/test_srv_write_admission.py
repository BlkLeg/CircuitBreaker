"""SRV-03: while the lifecycle is not READY, the server refuses writes — and only writes.

`test_health_degraded.py` proves the guard against the *dependency* half of the
contract (no database, no write) and against STOPPING for a single POST. This
suite pins the *lifecycle* half down completely, through the real application
and its real middleware stack, because that is the half the RISK-006 ledger
note found unevidenced:

* every unsafe method (POST, PUT, PATCH, DELETE) is refused with 503, a
  `{"detail": ...}` body and a `Retry-After` header in STARTING and STOPPING;
* the same writes are admitted in READY — and a refused write changes nothing;
* safe methods, CORS preflights, the health probes and WebSocket upgrades are
  untouched in every lifecycle state, because an operator and an orchestrator
  need exactly those while the process is starting or draining.

Dependencies are pinned healthy throughout, so any refusal seen here can only
have come from the lifecycle state.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send
from starlette.websockets import WebSocket

from app.core import health, write_admission
from app.core.server_state import ServerState, get_state, set_state

NOT_READY_STATES = (ServerState.STARTING, ServerState.STOPPING)
ALL_STATES = (ServerState.STARTING, ServerState.READY, ServerState.STOPPING)

#: One request per unsafe method. Paths are real routes so that, once
#: admitted, each request is answered by the router rather than by a 404.
UNSAFE_REQUESTS = (
    ("POST", "/api/v1/hardware"),
    ("PUT", "/api/v1/hardware/1"),
    ("PATCH", "/api/v1/hardware/1"),
    ("DELETE", "/api/v1/hardware/1"),
)

EXPECTED_ERROR_CODE = {
    ServerState.STARTING: write_admission.ERROR_CODE_NOT_READY,
    ServerState.STOPPING: write_admission.ERROR_CODE_DRAINING,
}


@pytest.fixture(autouse=True)
def _lifecycle_owned_by_this_test(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Arm the gate, pin dependencies healthy, and restore process state after.

    Lifecycle state, the armed flag and the cached health verdict are all
    process-global; leaking any of them would decide the next test's outcome.
    """
    import app.core.redis as redis_module

    previous_state = get_state()
    previous_armed = write_admission.is_armed()

    async def _redis_up() -> bool:
        return True

    monkeypatch.setattr(health, "_probe_db", lambda: "ok")
    monkeypatch.setattr(redis_module, "redis_health", _redis_up)
    set_state(ServerState.READY)
    write_admission.arm()
    health.reset_cache()
    yield
    set_state(previous_state)
    health.reset_cache()
    if previous_armed:
        write_admission.arm()
    else:
        write_admission.disarm()


def _assert_refused(response: Response, state: ServerState) -> None:
    """The refusal contract: 503, a human-readable detail, a retry hint."""
    assert response.status_code == 503
    body = response.json()
    assert isinstance(body.get("detail"), str) and body["detail"]
    assert body["error_code"] == EXPECTED_ERROR_CODE[state]
    assert body["health"] == state.value
    retry_after = response.headers["Retry-After"]
    assert retry_after.isdigit() and int(retry_after) > 0


# ── Unsafe methods ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("state", NOT_READY_STATES, ids=lambda s: s.value)
@pytest.mark.parametrize(("method", "path"), UNSAFE_REQUESTS, ids=lambda v: v)
async def test_every_unsafe_method_is_refused_while_not_ready(
    client: AsyncClient, state: ServerState, method: str, path: str
) -> None:
    set_state(state)

    response = await client.request(method, path, json={"name": "nas"})

    _assert_refused(response, state)
    # Registered inside SecurityHeadersMiddleware: the refusal is still a
    # response this server sends, and carries the same hardening headers.
    assert response.headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize(("method", "path"), UNSAFE_REQUESTS, ids=lambda v: v)
async def test_unsafe_methods_reach_the_router_when_ready(
    client: AsyncClient, method: str, path: str
) -> None:
    """Unauthenticated, so the router answers 401/403 — the point is that the
    request got past admission control to be answered at all."""
    set_state(ServerState.READY)

    response = await client.request(method, path, json={"name": "nas"})

    assert response.status_code in (401, 403)
    assert "error_code" not in response.json() or response.json()["error_code"] not in (
        write_admission.ERROR_CODE_NOT_READY,
        write_admission.ERROR_CODE_DRAINING,
    )


async def test_an_authenticated_write_succeeds_when_ready_and_is_refused_otherwise(
    client: AsyncClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    """End to end with a real, authorised write: READY persists it, STARTING
    and STOPPING refuse it *and persist nothing* — a 503 that had already
    written would be worse than no guard, because the client will retry."""
    from app.db.models import Hardware

    set_state(ServerState.READY)
    created = await client.post(
        "/api/v1/hardware", json={"name": "srv03-ready"}, headers=auth_headers
    )
    assert created.status_code in (200, 201), created.text
    assert (
        db_session.execute(
            select(Hardware).where(Hardware.name == "srv03-ready")
        ).scalar_one_or_none()
        is not None
    ), "the READY write did not persist, so the refusals below would prove nothing"

    for state in NOT_READY_STATES:
        set_state(state)
        name = f"srv03-{state.value}"
        refused = await client.post("/api/v1/hardware", json={"name": name}, headers=auth_headers)
        _assert_refused(refused, state)
        persisted = db_session.execute(
            select(Hardware).where(Hardware.name == name)
        ).scalar_one_or_none()
        assert persisted is None, f"a write refused in {state.value} was persisted"


# ── Safe methods ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("state", ALL_STATES, ids=lambda s: s.value)
async def test_reads_are_served_in_every_lifecycle_state(
    client: AsyncClient, auth_headers: dict[str, str], state: ServerState
) -> None:
    set_state(state)

    listed = await client.get("/api/v1/hardware", headers=auth_headers)
    probed = await client.head("/api/v1/livez")

    assert listed.status_code == 200, listed.text
    assert isinstance(listed.json(), list | dict)
    assert probed.status_code == 200


@pytest.mark.parametrize("state", ALL_STATES, ids=lambda s: s.value)
async def test_cors_preflight_is_never_refused(client: AsyncClient, state: ServerState) -> None:
    """A preflight is OPTIONS, not a write. The real app configures no allowed
    origin under test, so CORSMiddleware itself answers — with its own 400,
    never the guard's 503."""
    set_state(state)

    response = await client.options(
        "/api/v1/hardware",
        headers={"Origin": "https://ui.example", "Access-Control-Request-Method": "POST"},
    )

    assert response.status_code != 503
    assert "Retry-After" not in response.headers


@pytest.mark.parametrize("state", NOT_READY_STATES, ids=lambda s: s.value)
def test_cors_preflight_for_a_write_succeeds_while_writes_are_refused(state: ServerState) -> None:
    """The same ordering the real app uses — CORS inside the guard — with an
    allowed origin, so the preflight's *success* is observable: the browser is
    told the write is permitted in principle, and the write itself is what
    gets the 503."""

    async def _create(_: Request) -> JSONResponse:
        return JSONResponse({"created": True}, status_code=201)

    app = Starlette(
        routes=[Route("/api/v1/things", _create, methods=["POST"])],
        middleware=[
            Middleware(write_admission.WriteAdmissionMiddleware),
            Middleware(
                CORSMiddleware,
                allow_origins=["https://ui.example"],
                allow_methods=["POST", "OPTIONS"],
            ),
        ],
    )
    set_state(state)

    tc = TestClient(app)
    preflight = tc.options(
        "/api/v1/things",
        headers={"Origin": "https://ui.example", "Access-Control-Request-Method": "POST"},
    )
    write = tc.post("/api/v1/things", headers={"Origin": "https://ui.example"})

    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "https://ui.example"
    _assert_refused(write, state)


# ── Health and probes ──────────────────────────────────────────────────────


@pytest.mark.parametrize("state", NOT_READY_STATES, ids=lambda s: s.value)
async def test_health_endpoints_answer_for_themselves_while_writes_are_refused(
    client: AsyncClient, state: ServerState
) -> None:
    """Each probe returns its *own* verdict in every state — never the guard's.
    startupz and readyz legitimately return 503 here; what they must not
    return is the admission refusal."""
    set_state(state)

    expected = {
        "/api/v1/livez": 200,
        "/api/v1/startupz": 503 if state is ServerState.STARTING else 200,
        "/api/v1/readyz": 503,
        "/api/v1/health": 200,
    }
    for path, status in expected.items():
        response = await client.get(path)
        assert response.status_code == status, path
        assert "error_code" not in response.json(), path

    # Exempt by path, not only by method: an unsupported method on a probe is
    # answered by the router (405), not refused by admission control.
    assert (await client.post("/api/v1/livez")).status_code == 405


# ── WebSockets ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("state", NOT_READY_STATES, ids=lambda s: s.value)
def test_a_websocket_upgrade_reaches_its_route_while_writes_are_refused(
    state: ServerState, app_cfg: object, db_session: object
) -> None:
    """Agent links, enrolment and the UI streams are WebSockets; the lifespan
    drains them, admission control must not refuse them. Against the real app
    and the agent enrolment endpoint, which is unauthenticated by design: the
    upgrade is accepted, and the route itself then closes on a first frame
    that is not a Noise handshake — which it can only do if the upgrade got
    through the middleware stack."""
    from app.main import app

    set_state(state)

    # No `with`: the real lifespan would overwrite the state under test.
    tc = TestClient(app)
    with tc.websocket_connect("/api/v1/agents/enroll") as ws:
        ws.send_text("not-a-noise-handshake")
        message = ws.receive()

    assert message["type"] == "websocket.close"
    # 1008: the route rejected the malformed handshake. 1013: the route's own
    # per-IP enrolment attempt limiter answered. Both are the route speaking.
    assert message["code"] in (1008, 1013)


async def test_non_http_scopes_pass_through_untouched() -> None:
    """At the ASGI level: a websocket (or lifespan) scope is handed straight
    to the wrapped app, even with the gate armed and the process draining."""
    set_state(ServerState.STOPPING)
    seen: list[str] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["type"])

    async def receive() -> Message:
        return {"type": "websocket.connect"}

    async def send(message: Message) -> None:
        raise AssertionError(f"the guard answered a non-http scope: {message}")

    guard = write_admission.WriteAdmissionMiddleware(inner)
    for scope_type in ("websocket", "lifespan"):
        await guard(
            {"type": scope_type, "path": "/api/v1/agents/link", "method": "POST"}, receive, send
        )

    assert seen == ["websocket", "lifespan"]


def test_a_minimal_websocket_app_is_served_while_draining() -> None:
    """The same guarantee without any of the real app's auth in the way: a
    WebSocket under /api/ completes a full echo round trip while STOPPING."""

    async def _echo(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_text(await websocket.receive_text())
        await websocket.close()

    app = Starlette(
        routes=[WebSocketRoute("/api/v1/echo", _echo)],
        middleware=[Middleware(write_admission.WriteAdmissionMiddleware)],
    )
    set_state(ServerState.STOPPING)

    with TestClient(app).websocket_connect("/api/v1/echo") as ws:
        ws.send_text("ping")
        assert ws.receive_text() == "ping"


# ── The guard itself must not become the outage ────────────────────────────


async def test_a_slow_database_probe_does_not_stall_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard probes the database on the write path. A black-holed database
    holds a synchronous connect for the whole TCP timeout; on the event loop
    that would freeze every request — /livez included — and turn a database
    outage into a restart loop. The probe must run off the loop."""
    probe_s = 0.5

    def _slow_probe() -> str:
        time.sleep(probe_s)
        return "error"

    monkeypatch.setattr(health, "_probe_db", _slow_probe)
    ticks = 0

    async def _ticker() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    ticker = asyncio.create_task(_ticker())
    try:
        snapshot = await health.current_health(max_age_s=0.0)
    finally:
        ticker.cancel()

    assert snapshot.writes_permitted is False
    # A blocked loop yields ~0 ticks across the probe; a free one yields ~50.
    assert ticks >= 10, f"event loop ran only {ticks} ticks during a {probe_s}s probe"
