"""Health endpoint contract.

The endpoint answers liveness, not correctness. It is polled by the Docker
HEALTHCHECK, the reverse proxy, ``deploy/setup.sh`` (which greps the body for
``"ready"``) and the frontend's ``useServerLifecycle`` hook, so it always
returns 200 with ``{state, ready, uptime_s, checks}`` — a dependency that is
down shows up as ``checks.db``/``checks.redis`` being ``"error"``, never as a
503. Build version and installed extensions are unauthenticated fingerprinting
material and are disclosed only to authenticated callers.

Superseded contract (pre-1.0): a flat ``{"status": "ok", ...}`` body with a 503
``{"status": "warming_up"}`` on schema drift. Nothing consumes that shape now.
"""


def test_health_endpoint_reports_liveness(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "ready"
    assert body["ready"] is True
    assert isinstance(body["uptime_s"], int)
    assert body["checks"]["db"] == "ok"
    # Anonymous callers get liveness only — see the module docstring.
    assert "version" not in body
    assert "timescaledb_available" not in body


def test_health_discloses_build_detail_to_an_authenticated_caller(client, auth_headers):
    from app.core.config import settings

    resp = client.get("/api/v1/health", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == settings.app_version
    assert "timescaledb_available" in body


def test_health_reports_schema_drift_as_a_failed_db_check(client, monkeypatch):
    """Migration drift must surface, but not by taking the server out of rotation.

    ``scan_jobs.error_reason`` is the readiness canary: the discovery endpoints
    serialize that column, so a database missing it is a broken deployment. The
    endpoint reports it as ``checks.db == "error"`` and still answers 200,
    because the orchestrator's healthcheck and the frontend both need this route
    to keep responding precisely when the database is the thing that is wrong.
    """
    import app.main as main_mod

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, stmt):
            if "error_reason" in str(stmt):
                raise Exception("column scan_jobs.error_reason does not exist")
            return None

    class _Engine:
        def connect(self):
            return _Conn()

    monkeypatch.setattr(main_mod, "engine", _Engine())
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["checks"]["db"] == "error"
    assert body["state"] == "ready"
