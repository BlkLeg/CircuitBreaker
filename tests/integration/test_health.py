def test_health_endpoint_ok(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "ok"


def test_health_reports_schema_drift_as_503(client, monkeypatch):
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
    assert resp.status_code == 503
    body = resp.json()
    assert body.get("status") == "warming_up"
    assert "scan_jobs.error_reason" in (body.get("detail") or "")
