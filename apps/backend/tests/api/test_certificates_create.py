"""What POST /certificates does when the requested type cannot be produced (INC-07).

The route used to have no failure path at all: creation always succeeded, because it fell
back to generating a self-signed certificate whatever type was asked for.
"""

from __future__ import annotations

import pytest

from app.db.models import Certificate


@pytest.mark.asyncio
async def test_imported_without_a_pem_is_a_422(client, auth_headers, db_session):
    resp = await client.post(
        "/api/v1/certificates",
        json={"domain": "imported-no-pem.example.com", "type": "imported"},
        headers=auth_headers,
    )

    assert resp.status_code == 422, resp.text
    assert "cert_pem" in resp.json()["detail"]
    assert (
        db_session.query(Certificate).filter_by(domain="imported-no-pem.example.com").count() == 0
    )


@pytest.mark.asyncio
async def test_an_unreadable_pem_is_a_422_not_a_500(client, auth_headers):
    resp = await client.post(
        "/api/v1/certificates",
        json={
            "domain": "bad-pem.example.com",
            "type": "imported",
            "cert_pem": "-- not a pem --",
            "key_pem": "-- not a key --",
        },
        headers=auth_headers,
    )

    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_an_unknown_type_never_reaches_the_service(client, auth_headers):
    resp = await client.post(
        "/api/v1/certificates",
        json={"domain": "weird.example.com", "type": "acme-v9"},
        headers=auth_headers,
    )

    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_letsencrypt_issuance_failure_is_a_502_with_no_row(
    client, auth_headers, monkeypatch, db_session
):
    from app.services import certificate_service as svc

    def _refuse(domain, **kwargs):
        raise svc.CertificateRenewalError("CB_TLS_EMAIL is not set")

    monkeypatch.setattr(svc, "issue_acme_certificate", _refuse, raising=False)

    resp = await client.post(
        "/api/v1/certificates",
        json={"domain": "le-fails.example.com", "type": "letsencrypt"},
        headers=auth_headers,
    )

    assert resp.status_code == 502, resp.text
    assert resp.json()["detail"] == "CB_TLS_EMAIL is not set"
    assert db_session.query(Certificate).filter_by(domain="le-fails.example.com").count() == 0
