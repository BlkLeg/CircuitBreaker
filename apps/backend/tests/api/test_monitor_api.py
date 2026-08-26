from datetime import UTC, datetime, timedelta

import pytest


async def _create(client, auth_headers, **overrides):
    payload = {
        "name": "edge web",
        "check_type": "http",
        "host": "192.0.2.7",
        "config": {"url": "http://192.0.2.7/health", "accepted_statuses": ["200-299"]},
        "interval_secs": 60,
        "max_retries": 2,
    }
    payload.update(overrides)
    return await client.post("/api/v1/monitors", headers=auth_headers, json=payload)


async def _headers_for_user(client, user) -> dict[str, str]:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "TestPassword123!"},
    )
    assert resp.status_code == 200
    token = resp.json()["token"]
    csrf = resp.cookies.get("cb_csrf", "test-csrf-token")
    return {"Authorization": f"Bearer {token}", "X-CSRF-Token": csrf}


def _monitor_read_paths(monitor_id: int) -> tuple[str, ...]:
    return (
        "/api/v1/monitors",
        "/api/v1/monitors/overview",
        "/api/v1/monitors/target-summary?target_type=hardware",
        f"/api/v1/monitors/{monitor_id}",
        f"/api/v1/monitors/{monitor_id}/events",
        f"/api/v1/monitors/{monitor_id}/history",
        f"/api/v1/monitors/{monitor_id}/probe-runs",
        f"/api/v1/monitors/{monitor_id}/uptime",
    )


def _api_token_headers(db_session, factories, raw_token: str, scopes: list[str]) -> dict[str, str]:
    from app.core.security import create_salted_api_token_hash
    from app.db.models import APIToken

    owner = factories.user(role="admin")
    db_session.add(
        APIToken(
            token_hash=create_salted_api_token_hash(raw_token),
            label=f"SEC-08 token {' '.join(scopes) or 'empty'}",
            created_by=owner.id,
            scopes=scopes,
        )
    )
    db_session.flush()
    return {"Authorization": f"Bearer {raw_token}"}


@pytest.mark.asyncio
async def test_monitor_read_routes_require_auth(client, auth_headers):
    mid = (await _create(client, auth_headers)).json()["id"]
    client.cookies.clear()

    for path in _monitor_read_paths(mid):
        resp = await client.get(path)
        assert resp.status_code == 401, path


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["viewer", "editor", "admin"])
async def test_monitor_read_routes_allow_authenticated_roles(client, factories, role):
    admin_headers = await _headers_for_user(client, factories.user(role="admin"))
    mid = (await _create(client, admin_headers)).json()["id"]
    headers = await _headers_for_user(client, factories.user(role=role))

    for path in _monitor_read_paths(mid):
        resp = await client.get(path, headers=headers)
        assert resp.status_code == 200, path


@pytest.mark.asyncio
async def test_monitor_writes_require_editor_level_role(client, factories):
    viewer_headers = await _headers_for_user(client, factories.user(role="viewer"))

    viewer_resp = await _create(client, viewer_headers)
    assert viewer_resp.status_code == 403

    editor_headers = await _headers_for_user(client, factories.user(role="editor"))
    editor_resp = await _create(client, editor_headers)
    assert editor_resp.status_code == 200


@pytest.mark.asyncio
async def test_monitor_reads_allow_demo_session(client, auth_headers, factories):
    mid = (await _create(client, auth_headers)).json()["id"]
    demo = factories.user(role="demo", demo_expires=datetime.now(UTC) + timedelta(hours=1))
    demo_headers = await _headers_for_user(client, demo)

    for path in _monitor_read_paths(mid):
        resp = await client.get(path, headers=demo_headers)
        assert resp.status_code == 200, path


@pytest.mark.asyncio
async def test_monitor_reads_reject_expired_demo_session(client, auth_headers, factories):
    mid = (await _create(client, auth_headers)).json()["id"]
    demo = factories.user(role="demo", demo_expires=datetime.now(UTC) - timedelta(minutes=1))
    expired_headers = await _headers_for_user(client, demo)

    for path in _monitor_read_paths(mid):
        resp = await client.get(path, headers=expired_headers)
        assert resp.status_code == 401, path


@pytest.mark.asyncio
async def test_monitor_reads_reject_expired_jwt(client, auth_headers, db_session, factories):
    mid = (await _create(client, auth_headers)).json()["id"]

    import jwt as pyjwt

    from app.core.security import SESSION_AUDIENCE
    from app.services.settings_service import get_or_create_settings

    user = factories.user(role="viewer")
    cfg = get_or_create_settings(db_session)
    token = pyjwt.encode(
        {
            "user_id": user.id,
            "exp": datetime.now(UTC) - timedelta(minutes=1),
            "aud": SESSION_AUDIENCE,
        },
        cfg.jwt_secret,
        algorithm="HS256",
    )

    for path in _monitor_read_paths(mid):
        resp = await client.get(path, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401, path


@pytest.mark.asyncio
async def test_monitor_reads_reject_revoked_session(client, factories):
    admin_headers = await _headers_for_user(client, factories.user(role="admin"))
    mid = (await _create(client, admin_headers)).json()["id"]

    viewer_headers = await _headers_for_user(client, factories.user(role="viewer"))
    logout = await client.post("/api/v1/auth/logout", headers=viewer_headers)
    assert logout.status_code == 204

    for path in _monitor_read_paths(mid):
        resp = await client.get(path, headers=viewer_headers)
        assert resp.status_code == 401, path


@pytest.mark.asyncio
async def test_monitor_reads_allow_service_api_token(client, auth_headers, db_session, factories):
    mid = (await _create(client, auth_headers)).json()["id"]
    raw_token = "sec3-monitor-read-token"
    token_headers = _api_token_headers(db_session, factories, raw_token, ["read:*"])

    for path in _monitor_read_paths(mid):
        resp = await client.get(path, headers=token_headers)
        assert resp.status_code == 200, path


@pytest.mark.asyncio
async def test_monitor_reads_reject_service_api_token_without_read_scope(
    client, auth_headers, db_session, factories
):
    mid = (await _create(client, auth_headers)).json()["id"]
    token_headers = _api_token_headers(
        db_session, factories, "sec8-monitor-write-only-token", ["write:*"]
    )

    for path in _monitor_read_paths(mid):
        resp = await client.get(path, headers=token_headers)
        assert resp.status_code == 403, path


@pytest.mark.asyncio
async def test_monitor_reads_reject_service_account_jwt_without_read_scope(
    client, auth_headers, db_session
):
    mid = (await _create(client, auth_headers)).json()["id"]

    from tests.helpers.service_account import mint_service_account_token

    token = mint_service_account_token(
        db_session, scopes=["write:*"], label="SEC-08 write-only service account", hours=1
    )

    for path in _monitor_read_paths(mid):
        resp = await client.get(path, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403, path


@pytest.mark.asyncio
async def test_monitor_reads_reject_agent_like_bearer_token(client, auth_headers):
    mid = (await _create(client, auth_headers)).json()["id"]

    for path in _monitor_read_paths(mid):
        resp = await client.get(
            path,
            headers={"Authorization": "Bearer agent-noise-protocol-identity"},
        )
        assert resp.status_code == 401, path


@pytest.mark.asyncio
async def test_monitor_reads_hide_wrong_tenant_target(client, auth_headers, factories, db_session):
    """SEC-08: upgraded tenant-tagged targets remain non-enumerable across tenants."""
    from app.db.models import Tenant

    tenant_a, tenant_b = Tenant(name="monitor-read-a"), Tenant(name="monitor-read-b")
    db_session.add_all([tenant_a, tenant_b])
    db_session.flush()
    hardware = factories.hardware(tenant_id=tenant_a.id, ip_address="192.0.2.88")
    created = await _create(
        client,
        auth_headers,
        name="tenant-scoped-monitor",
        target_type="hardware",
        target_id=hardware.id,
        host="192.0.2.88",
        check_type="icmp",
        config={},
    )
    mid = created.json()["id"]
    same_tenant_headers = await _headers_for_user(
        client, factories.user(role="viewer", tenant_id=tenant_a.id)
    )
    wrong_tenant_headers = await _headers_for_user(
        client, factories.user(role="viewer", tenant_id=tenant_b.id)
    )

    for path in _monitor_read_paths(mid):
        assert (await client.get(path, headers=same_tenant_headers)).status_code == 200, path

    listing = await client.get("/api/v1/monitors", headers=wrong_tenant_headers)
    assert listing.status_code == 200
    assert mid not in {row["id"] for row in listing.json()}

    overview = await client.get("/api/v1/monitors/overview", headers=wrong_tenant_headers)
    assert overview.status_code == 200
    assert mid not in {row["id"] for row in overview.json()}

    summary = await client.get(
        "/api/v1/monitors/target-summary?target_type=hardware",
        headers=wrong_tenant_headers,
    )
    assert summary.status_code == 200
    assert mid not in {row["monitor_id"] for row in summary.json()}

    for path in (
        f"/api/v1/monitors/{mid}",
        f"/api/v1/monitors/{mid}/events",
        f"/api/v1/monitors/{mid}/history",
        f"/api/v1/monitors/{mid}/probe-runs",
        f"/api/v1/monitors/{mid}/uptime",
    ):
        resp = await client.get(path, headers=wrong_tenant_headers)
        assert resp.status_code == 404, path


@pytest.mark.asyncio
async def test_create_and_get(client, auth_headers):
    resp = await _create(client, auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert body["config"]["url"] == "http://192.0.2.7/health"

    got = await client.get(f"/api/v1/monitors/{body['id']}", headers=auth_headers)
    assert got.status_code == 200
    assert got.json()["name"] == "edge web"


@pytest.mark.asyncio
async def test_create_invalid_config_422(client, auth_headers):
    resp = await _create(client, auth_headers, config={"nonsense": True})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_filter(client, auth_headers):
    await _create(client, auth_headers, name="linked", target_type="hardware", target_id=1)
    resp = await client.get(
        "/api/v1/monitors",
        headers=auth_headers,
        params={"target_type": "hardware", "target_id": 1},
    )
    assert resp.status_code == 200
    assert all(m["target_type"] == "hardware" for m in resp.json())


@pytest.mark.asyncio
async def test_pause_resume(client, auth_headers):
    mid = (await _create(client, auth_headers)).json()["id"]
    paused = await client.post(f"/api/v1/monitors/{mid}/pause", headers=auth_headers)
    assert paused.json()["enabled"] is False
    resumed = await client.post(f"/api/v1/monitors/{mid}/resume", headers=auth_headers)
    assert resumed.json()["enabled"] is True
    events = (await client.get(f"/api/v1/monitors/{mid}/events", headers=auth_headers)).json()
    assert {e["event_type"] for e in events} >= {"paused", "resumed"}


@pytest.mark.asyncio
async def test_missing_monitor_404(client, auth_headers):
    assert (await client.get("/api/v1/monitors/999999", headers=auth_headers)).status_code == 404
    assert (await client.delete("/api/v1/monitors/999999", headers=auth_headers)).status_code == 404


@pytest.mark.asyncio
async def test_uptime_and_history_empty_ok(client, auth_headers):
    mid = (await _create(client, auth_headers)).json()["id"]
    uptime = await client.get(f"/api/v1/monitors/{mid}/uptime", headers=auth_headers)
    assert uptime.json() == {
        "pct_24h": None,
        "pct_7d": None,
        "pct_30d": None,
        "pct_365d": None,
        "pct_total": None,
        "last_polled_at": None,
        # D-12: the window is fully unobserved, which the response says out loud
        # rather than leaving the reader to infer it from a null percentage.
        "coverage_24h": {"observed_minutes": 0, "window_minutes": 1440, "pct": 0.0},
        "coverage_7d": {"observed_minutes": 0, "window_minutes": 10080, "pct": 0.0},
        "coverage_30d": {"observed_minutes": 0, "window_minutes": 43200, "pct": 0.0},
    }
    history = await client.get(f"/api/v1/monitors/{mid}/history", headers=auth_headers)
    assert history.json() == []


# ── Target-scoped routes (inventory pages, drawers, map) ─────────────────────


@pytest.mark.asyncio
async def test_target_quick_monitor_hardware(client, auth_headers, factories):
    hw = factories.hardware(ip_address="192.0.2.50")
    resp = await client.post(f"/api/v1/monitors/target/hardware/{hw.id}", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["check_type"] == "icmp"
    assert body["target_type"] == "hardware" and body["target_id"] == hw.id

    # idempotent per (hardware, check_type)
    again = await client.post(f"/api/v1/monitors/target/hardware/{hw.id}", headers=auth_headers)
    assert again.json()["id"] == body["id"]

    for action in ("pause", "resume", "check"):
        resp = await client.post(
            f"/api/v1/monitors/target/hardware/{hw.id}/{action}", headers=auth_headers
        )
        assert resp.status_code == 200, action


@pytest.mark.asyncio
async def test_target_quick_monitor_missing_404(client, auth_headers):
    assert (
        await client.post("/api/v1/monitors/target/hardware/999999", headers=auth_headers)
    ).status_code == 404
    assert (
        await client.post("/api/v1/monitors/target/hardware/999999/pause", headers=auth_headers)
    ).status_code == 404


@pytest.mark.asyncio
async def test_target_quick_monitor_compute_unit(client, auth_headers, factories):
    hw = factories.hardware(ip_address="192.0.2.60")
    cu = factories.compute_unit(hardware_id=hw.id, ip_address="192.0.2.61")

    resp = await client.post(f"/api/v1/monitors/target/compute_unit/{cu.id}", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["check_type"] == "icmp"
    assert body["target_type"] == "compute_unit" and body["target_id"] == cu.id

    # idempotent
    again = await client.post(f"/api/v1/monitors/target/compute_unit/{cu.id}", headers=auth_headers)
    assert again.json()["id"] == body["id"]

    for action in ("pause", "resume", "check"):
        resp = await client.post(
            f"/api/v1/monitors/target/compute_unit/{cu.id}/{action}", headers=auth_headers
        )
        assert resp.status_code == 200, action


@pytest.mark.asyncio
async def test_target_quick_monitor_service_uses_http(client, auth_headers, factories):
    svc = factories.service(name="grafana", url="https://grafana.lan/login")
    resp = await client.post(f"/api/v1/monitors/target/service/{svc.id}", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["check_type"] == "http"
    assert body["host"] == "grafana.lan"
    assert body["config"] == {"url": "https://grafana.lan/login"}


@pytest.mark.asyncio
async def test_target_quick_monitor_external_node(client, auth_headers, factories):
    node = factories.external_node(ip_address="api.example.com")
    resp = await client.post(
        f"/api/v1/monitors/target/external_node/{node.id}", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["check_type"] == "icmp"
    assert body["host"] == "api.example.com"
    assert body["target_type"] == "external_node" and body["target_id"] == node.id

    summary = await client.get(
        "/api/v1/monitors/target-summary",
        headers=auth_headers,
        params={"target_type": "external_node"},
    )
    assert [r["target_id"] for r in summary.json()] == [node.id]


@pytest.mark.asyncio
async def test_target_quick_monitor_accepts_overrides(client, auth_headers, factories):
    hw = factories.hardware(ip_address="192.0.2.62")
    resp = await client.post(
        f"/api/v1/monitors/target/hardware/{hw.id}",
        headers=auth_headers,
        json={"check_type": "tcp", "config": {"port": 22}},
    )
    assert resp.status_code == 200
    assert resp.json()["check_type"] == "tcp"
    assert resp.json()["config"] == {"port": 22}


@pytest.mark.asyncio
async def test_target_quick_monitor_invalid_config_422(client, auth_headers, factories):
    hw = factories.hardware(ip_address="192.0.2.63")
    resp = await client.post(
        f"/api/v1/monitors/target/hardware/{hw.id}",
        headers=auth_headers,
        json={"check_type": "tcp", "config": {"bogus": 1}},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_target_unknown_type_422(client, auth_headers):
    resp = await client.post("/api/v1/monitors/target/nonsense/1", headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_target_unprobeable_404(client, auth_headers, factories):
    svc = factories.service(name="no-address")
    assert (
        await client.post(f"/api/v1/monitors/target/service/{svc.id}", headers=auth_headers)
    ).status_code == 404
    assert (
        await client.post("/api/v1/monitors/target/compute_unit/999999", headers=auth_headers)
    ).status_code == 404
    assert (
        await client.post("/api/v1/monitors/target/service/999999/pause", headers=auth_headers)
    ).status_code == 404


@pytest.mark.asyncio
async def test_target_summary(client, auth_headers, factories):
    hw = factories.hardware(ip_address="192.0.2.64")
    cu = factories.compute_unit(hardware_id=hw.id, ip_address="192.0.2.65")
    await client.post(f"/api/v1/monitors/target/compute_unit/{cu.id}", headers=auth_headers)

    resp = await client.get(
        "/api/v1/monitors/target-summary",
        headers=auth_headers,
        params={"target_type": "compute_unit"},
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["target_id"] == cu.id
    assert rows[0]["enabled"] is True
    assert rows[0]["status"] == "pending"
    assert rows[0]["monitor_ids"] == [rows[0]["monitor_id"]]

    scoped = await client.get(
        "/api/v1/monitors/target-summary",
        headers=auth_headers,
        params={"target_type": "compute_unit", "target_ids": [999999]},
    )
    assert scoped.json() == []

    bad = await client.get(
        "/api/v1/monitors/target-summary", headers=auth_headers, params={"target_type": "nope"}
    )
    assert bad.status_code == 422


# ── Overview (the dashboard's single fetch) ──────────────────────────────────


def _sample(mid, value, ts):
    from app.db.models import TelemetryTimeseries

    return TelemetryTimeseries(
        entity_type="monitor",
        entity_id=0,
        item_id=mid,
        metric="latency_ms",
        value=value,
        source="monitor",
        ts=ts,
    )


def _event(mid, status, msg, ts):
    from app.db.models import MonitorEvent

    return MonitorEvent(item_id=mid, event_type=status, status_to=status, msg=msg, created_at=ts)


@pytest.mark.asyncio
async def test_overview_includes_series_and_checks(client, auth_headers, db_session):
    mid = (await _create(client, auth_headers, name="overview-target")).json()["id"]
    base = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
    for i, value in enumerate([10.0, 20.0, 30.0]):
        db_session.add(_sample(mid, value, base + timedelta(minutes=i)))
    for i, status in enumerate(["up", "down", "up"]):
        db_session.add(_event(mid, status, f"event {i}", base + timedelta(minutes=i)))
    db_session.commit()

    resp = await client.get("/api/v1/monitors/overview", headers=auth_headers)
    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["id"] == mid)

    # every MonitorRead field the page renders is still present
    assert row["name"] == "overview-target"
    assert row["check_type"] == "http"
    assert row["status"] == "pending"

    # latency series is oldest → newest, for the sparkline
    assert row["latency_series"] == [10.0, 20.0, 30.0]

    # checks are newest first, matching GET /events and CheckHistoryBar
    assert [c["msg"] for c in row["recent_checks"]] == ["event 2", "event 1", "event 0"]
    assert row["recent_checks"][0]["status_to"] == "up"
    assert set(row["recent_checks"][0]) == {"id", "status_to", "msg", "created_at"}


@pytest.mark.asyncio
async def test_overview_caps_series_lengths(client, auth_headers, db_session):
    mid = (await _create(client, auth_headers, name="chatty")).json()["id"]
    base = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
    for i in range(30):
        db_session.add(_sample(mid, float(i), base + timedelta(seconds=i)))
        db_session.add(_event(mid, "up", f"e{i}", base + timedelta(seconds=i)))
    db_session.commit()

    row = next(
        r
        for r in (await client.get("/api/v1/monitors/overview", headers=auth_headers)).json()
        if r["id"] == mid
    )
    assert len(row["latency_series"]) == 12
    assert row["latency_series"] == [float(i) for i in range(18, 30)]  # newest 12, oldest first
    assert len(row["recent_checks"]) == 20
    assert row["recent_checks"][0]["msg"] == "e29"  # newest first


@pytest.mark.asyncio
async def test_overview_empty_series_for_fresh_monitor(client, auth_headers):
    mid = (await _create(client, auth_headers, name="fresh")).json()["id"]
    row = next(
        r
        for r in (await client.get("/api/v1/monitors/overview", headers=auth_headers)).json()
        if r["id"] == mid
    )
    assert row["latency_series"] == []
    assert row["recent_checks"] == []


@pytest.mark.asyncio
async def test_overview_route_wins_over_monitor_id(client, auth_headers):
    """ "/overview" must not be parsed as a monitor id."""
    resp = await client.get("/api/v1/monitors/overview", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── Slice 3 §7: the probe vantage on the monitor API ─────────────────────────
# `probe_agent_id` is the only writable half; everything else in the probe block
# is server-derived and must survive being echoed back by a frontend that sends
# the whole form verbatim.


class _FakeRedis:
    """The two reads `is_agent_online` / `get_agent_connection_owner` make."""

    def __init__(self, store: dict[str, str]) -> None:
        self._store = store

    async def exists(self, key: str) -> int:
        return 1 if key in self._store else 0

    async def get(self, key: str) -> str | None:
        return self._store.get(key)


@pytest.fixture
def presence(monkeypatch):
    """A Redis double plus a `mark(agent)` helper that brings one agent online.

    Nothing is online until a test says so, so "offline" is the default and the
    check-now 409 path is exercised without depending on a live Redis.
    """
    store: dict[str, str] = {}

    async def _get_redis():
        return _FakeRedis(store)

    monkeypatch.setattr("app.core.redis.get_redis", _get_redis)

    def mark(agent, worker: str = "worker-1") -> None:
        store[f"agent:presence:{agent.id}"] = "{}"
        store[f"agent:connection:{agent.id}"] = worker

    return mark


@pytest.fixture
def nats_publish(monkeypatch):
    """Record every JetStream publish and report success.

    The real `js_publish` returns False with no broker, which is
    indistinguishable from "never called" — and "never called" is exactly the
    regression these tests exist to catch, so it has to be observable.
    """
    published: list[tuple[str, dict]] = []

    async def _publish(subject: str, payload: dict) -> bool:
        published.append((subject, payload))
        return True

    from app.core.nats_client import nats_client

    monkeypatch.setattr(nats_client, "js_publish", _publish)
    return published


def _probe_agent(factories, name: str = "branch-office", **kwargs):
    """An agent that passes every §2 precondition except liveness."""
    agent = factories.agent(status="active", name=name, **kwargs)
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=True)
    factories.agent_network(agent)  # 10.0.0.5/24 -> derived scope 10.0.0.0/24
    factories.agent_capability_readiness(agent, collector="probe.icmp", state="ready")
    return agent


async def _create_icmp(client, auth_headers, **overrides):
    return await _create(
        client,
        auth_headers,
        check_type="icmp",
        host="10.0.0.9",
        config={},
        **overrides,
    )


@pytest.mark.asyncio
async def test_create_with_probe_agent_id_persists_and_reads_back(client, auth_headers, factories):
    agent = _probe_agent(factories)

    resp = await _create_icmp(client, auth_headers, probe_agent_id=agent.id)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["probe_agent_id"] == agent.id
    assert body["probe_mode"] == "agent"
    assert body["probe_agent"] == {"id": agent.id, "name": "branch-office"}
    assert body["probe_execution_status"] is None
    assert body["probe_execution_reason"] is None
    assert body["probe_last_dispatched_at"] is None
    assert body["probe_last_result_at"] is None

    got = await client.get(f"/api/v1/monitors/{body['id']}", headers=auth_headers)
    assert got.json()["probe_agent_id"] == agent.id
    assert got.json()["probe_agent"]["name"] == "branch-office"


@pytest.mark.asyncio
async def test_patch_probe_agent_id_reassigns(client, auth_headers, factories):
    first = _probe_agent(factories, name="office-a")
    second = _probe_agent(factories, name="office-b")
    mid = (await _create_icmp(client, auth_headers, probe_agent_id=first.id)).json()["id"]

    moved = await client.patch(
        f"/api/v1/monitors/{mid}", headers=auth_headers, json={"probe_agent_id": second.id}
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["probe_agent_id"] == second.id
    assert moved.json()["probe_agent"]["name"] == "office-b"

    # §1: unassigning is explicit and returns the monitor to server execution.
    home = await client.patch(
        f"/api/v1/monitors/{mid}", headers=auth_headers, json={"probe_agent_id": None}
    )
    assert home.json()["probe_agent_id"] is None
    assert home.json()["probe_mode"] == "server"
    assert home.json()["probe_agent"] is None


@pytest.mark.asyncio
async def test_patch_with_echoed_readonly_probe_fields_does_not_change_the_assignment(
    client, auth_headers, factories, db_session
):
    """`MonitorUpdate` is not `extra="forbid"` and the form is sent verbatim, so
    the server-derived half of the probe block has to be inert on the way in."""
    from app.db.models import MonitorItem

    agent = _probe_agent(factories)
    mid = (await _create_icmp(client, auth_headers, probe_agent_id=agent.id)).json()["id"]
    db_session.get(MonitorItem, mid).probe_execution_status = "ready"
    db_session.flush()

    resp = await client.patch(
        f"/api/v1/monitors/{mid}",
        headers=auth_headers,
        json={
            "name": "renamed",
            "probe_agent_id": agent.id,  # echoed unchanged — must not reassign
            "probe_mode": "server",
            "probe_agent": None,
            "probe_execution_status": "unavailable",
            "probe_execution_reason": "agent_offline",
            "probe_last_dispatched_at": "2026-01-01T00:00:00Z",
            "probe_last_result_at": "2026-01-01T00:00:00Z",
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "renamed"
    assert body["probe_agent_id"] == agent.id
    assert body["probe_mode"] == "agent"
    assert body["probe_execution_status"] == "ready"
    assert body["probe_execution_reason"] is None
    assert body["probe_last_dispatched_at"] is None
    assert body["probe_last_result_at"] is None


@pytest.mark.asyncio
async def test_probe_mode_is_server_when_unassigned_and_agent_when_assigned(
    client, auth_headers, factories
):
    server_body = (await _create_icmp(client, auth_headers, name="server-side")).json()
    assert server_body["probe_mode"] == "server"
    assert server_body["probe_agent"] is None
    assert server_body["probe_agent_id"] is None

    agent = _probe_agent(factories)
    agent_body = (
        await _create_icmp(client, auth_headers, name="agent-side", probe_agent_id=agent.id)
    ).json()
    assert agent_body["probe_mode"] == "agent"

    overview = await client.get("/api/v1/monitors/overview", headers=auth_headers)
    modes = {row["id"]: row["probe_mode"] for row in overview.json()}
    assert modes[server_body["id"]] == "server"
    assert modes[agent_body["id"]] == "agent"


@pytest.mark.asyncio
async def test_check_now_returns_409_with_the_reason_when_the_agent_is_offline(
    client, auth_headers, factories, presence
):
    """D-14: §2 forbids falling back to the server, so the only honest answer is
    a refusal that names the availability reason."""
    agent = _probe_agent(factories)  # presence deliberately not marked
    mid = (await _create_icmp(client, auth_headers, probe_agent_id=agent.id)).json()["id"]

    resp = await client.post(f"/api/v1/monitors/{mid}/check", headers=auth_headers)

    assert resp.status_code == 409
    assert resp.json()["detail"] == "agent_offline"


@pytest.mark.asyncio
async def test_check_now_on_a_server_monitor_still_returns_200(client, auth_headers, presence):
    mid = (await _create_icmp(client, auth_headers)).json()["id"]

    resp = await client.post(f"/api/v1/monitors/{mid}/check", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["id"] == mid


@pytest.mark.asyncio
async def test_check_now_on_an_eligible_agent_opens_a_run(
    client, auth_headers, factories, db_session, presence, nats_publish
):
    from app.core.subjects import MONITOR_PROBE_REMOTE
    from app.db.models import MonitorProbeRun

    agent = _probe_agent(factories)
    presence(agent)
    mid = (await _create_icmp(client, auth_headers, probe_agent_id=agent.id)).json()["id"]

    resp = await client.post(f"/api/v1/monitors/{mid}/check", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    runs = db_session.query(MonitorProbeRun).filter(MonitorProbeRun.monitor_id == mid).all()
    assert [r.status for r in runs] == ["queued"]
    assert runs[0].agent_id == agent.id
    # A run nobody was told about is a wedge, not a check: it holds
    # uq_monitor_probe_runs_active until the reconciliation pass expires it.
    assert nats_publish == [(MONITOR_PROBE_REMOTE, {"run_id": runs[0].run_id})]


@pytest.mark.asyncio
async def test_check_now_that_cannot_be_dispatched_answers_409_and_closes_the_run(
    client, auth_headers, factories, db_session, presence, monkeypatch
):
    """D-14: "accepted" is a claim this route must be able to stand behind, so a
    publish that never left the building is a refusal, not a 200 — and the run
    it opened has to be closed instead of holding the active-run index."""
    from app.core.nats_client import nats_client
    from app.db.models import MonitorItem, MonitorProbeRun

    async def _fails(subject: str, payload: dict) -> bool:
        return False

    monkeypatch.setattr(nats_client, "js_publish", _fails)

    agent = _probe_agent(factories)
    presence(agent)
    mid = (await _create_icmp(client, auth_headers, probe_agent_id=agent.id)).json()["id"]

    resp = await client.post(f"/api/v1/monitors/{mid}/check", headers=auth_headers)

    assert resp.status_code == 409
    assert resp.json()["detail"] == "dispatch_failed"
    db_session.expire_all()
    runs = db_session.query(MonitorProbeRun).filter(MonitorProbeRun.monitor_id == mid).all()
    assert [r.status for r in runs] == ["execution_error"]
    assert runs[0].error_code == "dispatch_failed"
    assert db_session.get(MonitorItem, mid).probe_execution_status == "unavailable"


@pytest.mark.asyncio
async def test_probe_runs_endpoint_is_bounded_and_newest_first(
    client, auth_headers, factories, db_session
):
    from app.db.models import MonitorItem

    agent = _probe_agent(factories)
    mid = (await _create_icmp(client, auth_headers, probe_agent_id=agent.id)).json()["id"]
    monitor = db_session.get(MonitorItem, mid)
    base = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)
    for i in range(4):
        factories.monitor_probe_run(
            monitor,
            agent,
            status="completed",
            outcome="completed",
            msg=f"run {i}",
            created_at=base + timedelta(minutes=i),
            scheduled_at=base + timedelta(minutes=i),
        )
    db_session.flush()

    resp = await client.get(
        f"/api/v1/monitors/{mid}/probe-runs", headers=auth_headers, params={"limit": 2}
    )

    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert [r["msg"] for r in rows] == ["run 3", "run 2"]
    assert rows[0]["status"] == "completed"
    assert rows[0]["outcome"] == "completed"
    assert set(rows[0]) >= {"run_id", "agent_id", "status", "created_at", "scheduled_at"}

    assert (
        await client.get("/api/v1/monitors/999999/probe-runs", headers=auth_headers)
    ).status_code == 404


@pytest.mark.asyncio
async def test_assignment_write_requires_editor_level_auth(client, viewer_headers, factories):
    """D-15: `require_write_auth` already *is* editor-level; no new dependency."""
    agent = _probe_agent(factories)
    monitor = factories.monitor_item(host="10.0.0.9", check_type="icmp")

    patched = await client.patch(
        f"/api/v1/monitors/{monitor.id}", headers=viewer_headers, json={"probe_agent_id": agent.id}
    )
    assert patched.status_code == 403

    created = await client.post(
        "/api/v1/monitors",
        headers=viewer_headers,
        json={
            "name": "viewer-assigned",
            "check_type": "icmp",
            "host": "10.0.0.9",
            "config": {},
            "probe_agent_id": agent.id,
        },
    )
    assert created.status_code == 403


@pytest.mark.asyncio
async def test_cross_tenant_assignment_is_rejected(client, auth_headers, factories, db_session):
    """D-9: refuse only when both sides carry a tenant and they differ."""
    from app.db.models import Tenant

    tenant_a, tenant_b = Tenant(name="probe-api-a"), Tenant(name="probe-api-b")
    db_session.add_all([tenant_a, tenant_b])
    db_session.flush()
    agent = _probe_agent(factories, tenant_id=tenant_a.id)
    hardware = factories.hardware(tenant_id=tenant_b.id, ip_address="10.0.0.9")

    resp = await client.post(
        "/api/v1/monitors",
        headers=auth_headers,
        json={
            "name": "cross-tenant",
            "check_type": "icmp",
            "host": "10.0.0.9",
            "config": {},
            "target_type": "hardware",
            "target_id": hardware.id,
            "probe_agent_id": agent.id,
        },
    )
    assert resp.status_code == 422
    assert "tenant" in str(resp.json()["detail"]).lower()

    same_tenant = factories.hardware(tenant_id=tenant_a.id, ip_address="10.0.0.10")
    ok = await client.post(
        "/api/v1/monitors",
        headers=auth_headers,
        json={
            "name": "same-tenant",
            "check_type": "icmp",
            "host": "10.0.0.10",
            "config": {},
            "target_type": "hardware",
            "target_id": same_tenant.id,
            "probe_agent_id": agent.id,
        },
    )
    assert ok.status_code == 200, ok.text


@pytest.mark.asyncio
async def test_assignment_to_an_unknown_agent_is_rejected(client, auth_headers):
    resp = await _create_icmp(client, auth_headers, probe_agent_id=999999)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_target_check_routes_an_assigned_monitor_to_its_agent_not_the_server(
    client, auth_headers, factories, db_session, nats_publish
):
    """§2 allows no automatic fallback: a target-scoped "check now" must not
    quietly have the server execute a check the operator assigned to an agent."""
    from app.core.subjects import MONITOR_PROBE_REMOTE
    from app.db.models import MonitorProbeRun

    agent = _probe_agent(factories)
    hw = factories.hardware(ip_address="10.0.0.9")
    created = await client.post(f"/api/v1/monitors/target/hardware/{hw.id}", headers=auth_headers)
    mid = created.json()["id"]
    assigned = await client.patch(
        f"/api/v1/monitors/{mid}", headers=auth_headers, json={"probe_agent_id": agent.id}
    )
    assert assigned.status_code == 200, assigned.text

    resp = await client.post(
        f"/api/v1/monitors/target/hardware/{hw.id}/check", headers=auth_headers
    )

    assert resp.status_code == 200
    runs = db_session.query(MonitorProbeRun).filter(MonitorProbeRun.monitor_id == mid).all()
    assert [r.status for r in runs] == ["queued"]
    assert runs[0].agent_id == agent.id
    assert nats_publish == [(MONITOR_PROBE_REMOTE, {"run_id": runs[0].run_id})]


@pytest.mark.asyncio
async def test_target_check_on_a_server_monitor_publishes_a_poll(
    client, auth_headers, factories, nats_publish
):
    """The server half of the same route: an unassigned monitor still has to
    reach `mon.poll.item`, or "check now" is a 200 that does nothing at all."""
    from app.core.subjects import MONITOR_POLL_ITEM

    hw = factories.hardware(ip_address="10.0.0.9")
    created = await client.post(f"/api/v1/monitors/target/hardware/{hw.id}", headers=auth_headers)
    mid = created.json()["id"]

    resp = await client.post(
        f"/api/v1/monitors/target/hardware/{hw.id}/check", headers=auth_headers
    )

    assert resp.status_code == 200
    assert [subject for subject, _ in nats_publish] == [MONITOR_POLL_ITEM]
    assert nats_publish[0][1]["item_id"] == mid


@pytest.mark.asyncio
async def test_target_check_closes_the_run_when_the_dispatch_publish_fails(
    client, auth_headers, factories, db_session, monkeypatch
):
    """An undispatchable run must not be left holding the active-run index.

    Otherwise the next due tick takes D-6's `previous_run_in_flight` skip and
    the D-5 reconciliation pass writes a spurious `result_timeout` ~50 s later.
    """
    from app.core.nats_client import nats_client
    from app.db.models import MonitorItem, MonitorProbeRun

    async def _fails(subject: str, payload: dict) -> bool:
        return False

    monkeypatch.setattr(nats_client, "js_publish", _fails)

    agent = _probe_agent(factories)
    hw = factories.hardware(ip_address="10.0.0.9")
    mid = (
        await client.post(f"/api/v1/monitors/target/hardware/{hw.id}", headers=auth_headers)
    ).json()["id"]
    await client.patch(
        f"/api/v1/monitors/{mid}", headers=auth_headers, json={"probe_agent_id": agent.id}
    )
    due_before = db_session.get(MonitorItem, mid).next_due_at

    resp = await client.post(
        f"/api/v1/monitors/target/hardware/{hw.id}/check", headers=auth_headers
    )

    assert resp.status_code == 200
    db_session.expire_all()
    runs = db_session.query(MonitorProbeRun).filter(MonitorProbeRun.monitor_id == mid).all()
    assert [r.status for r in runs] == ["execution_error"]
    assert runs[0].error_code == "dispatch_failed"
    assert runs[0].completed_at is not None
    monitor = db_session.get(MonitorItem, mid)
    assert monitor.probe_execution_status == "unavailable"
    assert monitor.probe_execution_reason == "dispatch_failed"
    # A manual check that could not be dispatched must not move the schedule.
    assert monitor.next_due_at == due_before
