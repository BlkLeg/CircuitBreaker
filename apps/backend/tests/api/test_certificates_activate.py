"""Activation is the operator's explicit choice about what this install serves."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_activate_marks_the_certificate_and_reports_the_reload(
    client, auth_headers, monkeypatch, tmp_path, db_session
):
    from app.db.models import Certificate
    from app.services import certificate_activation as act

    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(act, "_reload_tls", lambda: (True, "nginx reloaded via supervisorctl"))

    created = await client.post(
        "/api/v1/certificates",
        json={"domain": "a.example.com", "type": "selfsigned", "auto_renew": True},
        headers=auth_headers,
    )
    assert created.status_code == 200, created.text
    cert_id = created.json()["id"]

    resp = await client.post(f"/api/v1/certificates/{cert_id}/activate", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["written"] is True
    assert body["reloaded"] is True
    assert body["certificate"]["is_active"] is True
    assert (tmp_path / "tls" / "fullchain.pem").read_text().startswith("-----BEGIN CERTIFICATE")
    assert db_session.query(Certificate).filter(Certificate.is_active).count() == 1


@pytest.mark.asyncio
async def test_activate_reports_a_failed_reload_without_failing(
    client, auth_headers, monkeypatch, tmp_path
):
    """'Written but not reloaded' is a real state and must not look like success or error."""
    from app.services import certificate_activation as act

    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(act, "_reload_tls", lambda: (False, "no TLS server was found to reload"))

    created = await client.post(
        "/api/v1/certificates",
        json={"domain": "b.example.com", "type": "selfsigned", "auto_renew": True},
        headers=auth_headers,
    )
    cert_id = created.json()["id"]

    resp = await client.post(f"/api/v1/certificates/{cert_id}/activate", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["reloaded"] is False
    assert body["written"] is True
    assert body["detail"] == "no TLS server was found to reload"
    assert body["certificate"]["is_active"] is True


@pytest.mark.asyncio
async def test_activate_requires_admin(client, viewer_headers):
    resp = await client.post("/api/v1/certificates/1/activate", headers=viewer_headers)

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_activate_unknown_certificate_is_404(client, auth_headers):
    resp = await client.post("/api/v1/certificates/999999/activate", headers=auth_headers)

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_a_failed_renewal_is_not_a_200(client, auth_headers, monkeypatch):
    """The pre-fix code answered 200 with an unchanged expires_at."""
    from app.services import certificate_service as svc

    created = await client.post(
        "/api/v1/certificates",
        json={"domain": "c.example.com", "type": "selfsigned", "auto_renew": True},
        headers=auth_headers,
    )
    cert_id = created.json()["id"]
    before = created.json()["expires_at"]

    def _fail(db, cert):
        raise svc.CertificateRenewalError("certbot is not installed in this image")

    monkeypatch.setattr(svc, "renew_certificate", _fail)

    resp = await client.post(f"/api/v1/certificates/{cert_id}/renew", headers=auth_headers)

    assert resp.status_code != 200
    assert "certbot" in resp.text

    after = await client.get(f"/api/v1/certificates/{cert_id}", headers=auth_headers)
    assert after.json()["expires_at"] == before
