"""Tests for admin DB / backup API endpoints.

Routes (admin_db_router mounted at /api/v1/admin):
  GET   /api/v1/admin/db/health          — DB health (existing)
  POST  /api/v1/admin/db/backup          — pg_dump backup (existing)
  POST  /api/v1/admin/db/snapshot        — full-state snapshot
  GET   /api/v1/admin/db/snapshots       — list local snapshots
  GET   /api/v1/admin/settings/backup    — read backup S3 settings
  PUT   /api/v1/admin/settings/backup    — update backup S3 settings
  POST  /api/v1/admin/settings/backup/test — test S3 connection
"""

import pytest

pytestmark = pytest.mark.asyncio

_BASE = "/api/v1/admin"


# ── Existing endpoints (smoke) ─────────────────────────────────────────────────


async def test_db_health_unauthenticated_returns_401(client):
    resp = await client.get(f"{_BASE}/db/health")
    assert resp.status_code == 401


async def test_db_health_admin_returns_200(client, auth_headers):
    resp = await client.get(f"{_BASE}/db/health", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert "dialect" in body


# ── POST /db/snapshot ──────────────────────────────────────────────────────────


async def test_trigger_snapshot_returns_info(client, auth_headers, tmp_path, monkeypatch):
    """POST /admin/db/snapshot returns SnapshotInfo."""
    fake_tarball = tmp_path / "cb-snapshot-20260322-020000.tar.gz"
    fake_tarball.write_bytes(b"fake")

    async def mock_run_full_snapshot(db):  # type: ignore[no-untyped-def]
        return fake_tarball

    monkeypatch.setattr(
        "app.api.admin_db.run_full_snapshot",
        mock_run_full_snapshot,
    )

    resp = await client.post(
        f"{_BASE}/db/snapshot",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["filename"] == "cb-snapshot-20260322-020000.tar.gz"
    assert "size_mb" in data
    assert "created_at" in data


async def test_trigger_snapshot_unauthenticated_returns_401(client):
    resp = await client.post(f"{_BASE}/db/snapshot")
    assert resp.status_code == 401


# ── GET /db/snapshots ──────────────────────────────────────────────────────────


async def test_list_snapshots_returns_list(client, auth_headers, monkeypatch):
    """GET /admin/db/snapshots returns list of snapshots (empty when dir missing)."""
    from pathlib import Path

    monkeypatch.setattr(
        "app.services.db_backup.BACKUP_DIR",
        Path("/nonexistent"),
    )

    resp = await client.get(
        f"{_BASE}/db/snapshots",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "snapshots" in body
    assert isinstance(body["snapshots"], list)


async def test_list_snapshots_returns_files(client, auth_headers, tmp_path, monkeypatch):
    """GET /admin/db/snapshots enumerates cb-snapshot-*.tar.gz files."""
    import app.api.admin_db as admin_db_module

    # Create two fake snapshot files
    (tmp_path / "cb-snapshot-20260321-010000.tar.gz").write_bytes(b"x" * 1024)
    (tmp_path / "cb-snapshot-20260322-010000.tar.gz").write_bytes(b"x" * 2048)
    # Also create a non-matching file that should be ignored
    (tmp_path / "cb-20260322.sql.gz").write_bytes(b"ignore")

    monkeypatch.setattr(admin_db_module, "BACKUP_DIR", tmp_path)

    resp = await client.get(
        f"{_BASE}/db/snapshots",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    snapshots = resp.json()["snapshots"]
    assert len(snapshots) == 2
    filenames = [s["filename"] for s in snapshots]
    assert "cb-snapshot-20260321-010000.tar.gz" in filenames
    assert "cb-snapshot-20260322-010000.tar.gz" in filenames


async def test_list_snapshots_unauthenticated_returns_401(client):
    resp = await client.get(f"{_BASE}/db/snapshots")
    assert resp.status_code == 401


# ── GET /settings/backup ───────────────────────────────────────────────────────


async def test_get_backup_settings_returns_response(client, auth_headers):
    """GET /admin/settings/backup returns BackupSettingsResponse."""
    resp = await client.get(
        f"{_BASE}/settings/backup",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "backup_s3_bucket" in data
    assert "backup_s3_secret_key_set" in data
    assert "backup_s3_region" in data
    assert "backup_s3_prefix" in data
    assert "backup_s3_retention_count" in data
    assert "backup_local_retention_count" in data
    # Secret key must never be exposed
    assert "backup_s3_secret_key" not in data


async def test_get_backup_settings_defaults(client, auth_headers):
    """Default values are returned when nothing has been configured."""
    resp = await client.get(
        f"{_BASE}/settings/backup",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["backup_s3_secret_key_set"] is False
    assert data["backup_s3_region"] == "us-east-1"
    assert data["backup_s3_retention_count"] >= 1
    assert data["backup_local_retention_count"] >= 1


async def test_get_backup_settings_unauthenticated_returns_401(client):
    resp = await client.get(f"{_BASE}/settings/backup")
    assert resp.status_code == 401


# ── PUT /settings/backup ───────────────────────────────────────────────────────


async def test_update_backup_settings_partial_update(client, auth_headers):
    """PUT /admin/settings/backup applies PATCH semantics."""
    resp = await client.put(
        f"{_BASE}/settings/backup",
        headers=auth_headers,
        json={"backup_s3_bucket": "my-test-bucket", "backup_s3_region": "eu-west-1"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["backup_s3_bucket"] == "my-test-bucket"
    assert data["backup_s3_region"] == "eu-west-1"
    # Secret key not sent → should not be set
    assert data["backup_s3_secret_key_set"] is False

    # Second PUT: only update region; bucket should be unchanged
    resp2 = await client.put(
        f"{_BASE}/settings/backup",
        headers=auth_headers,
        json={"backup_s3_region": "us-west-2"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["backup_s3_bucket"] == "my-test-bucket"
    assert resp2.json()["backup_s3_region"] == "us-west-2"


async def test_update_backup_settings_secret_key_set(client, auth_headers):
    """Setting a secret key marks backup_s3_secret_key_set=True."""
    resp = await client.put(
        f"{_BASE}/settings/backup",
        headers=auth_headers,
        json={"backup_s3_bucket": "bucket-with-secret", "backup_s3_secret_key": "supersecret"},
    )
    assert resp.status_code == 200
    assert resp.json()["backup_s3_secret_key_set"] is True


async def test_update_backup_settings_clear_secret_key(client, auth_headers):
    """Sending empty string for secret key clears it."""
    # First set a key
    await client.put(
        f"{_BASE}/settings/backup",
        headers=auth_headers,
        json={"backup_s3_secret_key": "set-then-clear"},
    )
    # Now clear it
    resp = await client.put(
        f"{_BASE}/settings/backup",
        headers=auth_headers,
        json={"backup_s3_secret_key": ""},
    )
    assert resp.status_code == 200
    assert resp.json()["backup_s3_secret_key_set"] is False


async def test_update_backup_settings_retention_counts(client, auth_headers):
    """Retention count fields are updated correctly."""
    resp = await client.put(
        f"{_BASE}/settings/backup",
        headers=auth_headers,
        json={"backup_s3_retention_count": 14, "backup_local_retention_count": 3},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["backup_s3_retention_count"] == 14
    assert data["backup_local_retention_count"] == 3


async def test_update_backup_settings_unauthenticated_returns_401(client):
    resp = await client.put(f"{_BASE}/settings/backup", json={})
    assert resp.status_code == 401


async def test_update_backup_settings_viewer_returns_403(client, viewer_headers):
    resp = await client.put(
        f"{_BASE}/settings/backup",
        headers=viewer_headers,
        json={"backup_s3_bucket": "no-access"},
    )
    assert resp.status_code == 403


# ── POST /settings/backup/test ─────────────────────────────────────────────────


async def test_backup_connection_test_no_bucket_returns_400(client, auth_headers):
    """POST /settings/backup/test returns 400 when no bucket is configured."""
    # Ensure bucket is cleared first
    await client.put(
        f"{_BASE}/settings/backup",
        headers=auth_headers,
        json={"backup_s3_bucket": ""},
    )
    resp = await client.post(
        f"{_BASE}/settings/backup/test",
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "bucket" in resp.json()["detail"].lower()


async def test_backup_connection_test_s3_error_returns_502(client, auth_headers, monkeypatch):
    """POST /settings/backup/test returns 502 when S3 probe fails."""
    from app.services.backup.s3_client import S3Error

    async def mock_probe(self):  # type: ignore[no-untyped-def]
        raise S3Error("connection refused")

    monkeypatch.setattr(
        "app.services.backup.s3_client.S3Client.probe",
        mock_probe,
    )

    # Ensure a bucket is configured
    await client.put(
        f"{_BASE}/settings/backup",
        headers=auth_headers,
        json={"backup_s3_bucket": "test-bucket"},
    )

    resp = await client.post(
        f"{_BASE}/settings/backup/test",
        headers=auth_headers,
    )
    assert resp.status_code == 502
    assert "connection refused" in resp.json()["detail"]


async def test_backup_connection_test_unauthenticated_returns_401(client):
    resp = await client.post(f"{_BASE}/settings/backup/test")
    assert resp.status_code == 401
