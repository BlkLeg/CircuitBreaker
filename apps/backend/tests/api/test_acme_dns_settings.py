"""The DNS-01 provider surface: what an admin can set, and what comes back out.

The read contract is the one INC-06 established for notification sinks — a ``*_set`` flag
says whether a credential is stored, and the credential itself never leaves the server in
any form. The write contract is the other half of that: a form that renders the mask and
submits it back must be a no-op on the secret, or every unrelated edit destroys it.
"""

from __future__ import annotations

import pytest

_PATH = "/api/v1/settings/acme-dns"


@pytest.mark.asyncio
async def test_the_token_never_comes_back(client, auth_headers):
    await client.patch(
        _PATH,
        json={"provider": "cloudflare", "api_token": "cf-tok-SECRETVALUE"},
        headers=auth_headers,
    )

    resp = await client.get("/api/v1/settings", headers=auth_headers)

    assert resp.status_code == 200
    assert "cf-tok-SECRETVALUE" not in resp.text
    acme = resp.json()["acme_dns"]
    assert acme["provider"] == "cloudflare"
    assert acme["api_token_set"] is True


@pytest.mark.asyncio
async def test_unconfigured_reads_as_unconfigured(client, auth_headers):
    await client.patch(_PATH, json={"provider": None}, headers=auth_headers)

    acme = (await client.get("/api/v1/settings", headers=auth_headers)).json()["acme_dns"]

    assert acme["provider"] is None
    assert acme["api_token_set"] is False


@pytest.mark.asyncio
async def test_the_stored_credential_is_ciphertext(client, auth_headers, db_session):
    from app.db.models import AppSettings

    await client.patch(
        _PATH,
        json={"provider": "cloudflare", "api_token": "cf-tok-SECRETVALUE"},
        headers=auth_headers,
    )

    db_session.expire_all()
    cfg = db_session.get(AppSettings, 1)
    assert "cf-tok-SECRETVALUE" not in str(cfg.acme_dns_config)
    assert cfg.acme_dns_config["api_token_enc"]


@pytest.mark.asyncio
async def test_editing_a_neighbouring_field_keeps_the_secret(client, auth_headers, db_session):
    from app.services import acme_secrets

    await client.patch(
        _PATH,
        json={
            "provider": "rfc2136",
            "server": "ns1.example.com",
            "tsig_name": "cb-key",
            "tsig_secret": "s3cret",
        },
        headers=auth_headers,
    )

    resp = await client.patch(
        _PATH,
        json={"provider": "rfc2136", "server": "ns2.example.com"},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    creds = acme_secrets.load_dns_credentials(db_session)
    assert creds["server"] == "ns2.example.com"
    assert creds["tsig_secret"] == "s3cret"


@pytest.mark.asyncio
async def test_switching_provider_does_not_carry_the_old_credential(
    client, auth_headers, db_session
):
    """A Cloudflare token is not an RFC2136 key. Carrying one across would store a
    credential under a provider that cannot use it and report it as configured."""
    from app.services import acme_secrets

    await client.patch(
        _PATH,
        json={"provider": "cloudflare", "api_token": "cf-tok"},
        headers=auth_headers,
    )

    await client.patch(
        _PATH,
        json={
            "provider": "rfc2136",
            "server": "ns1.example.com",
            "tsig_name": "cb-key",
            "tsig_secret": "s3cret",
        },
        headers=auth_headers,
    )

    creds = acme_secrets.load_dns_credentials(db_session)
    assert creds["_provider"] == "rfc2136"
    assert "api_token" not in creds


@pytest.mark.asyncio
async def test_clearing_the_provider_removes_the_credential(client, auth_headers, db_session):
    """Turning DNS-01 off must not leave a zone credential on disk."""
    from app.services import acme_secrets

    await client.patch(
        _PATH, json={"provider": "cloudflare", "api_token": "cf-tok"}, headers=auth_headers
    )

    resp = await client.patch(_PATH, json={"provider": None}, headers=auth_headers)

    assert resp.status_code == 200
    assert acme_secrets.load_dns_credentials(db_session) is None


@pytest.mark.asyncio
async def test_an_unsupported_provider_is_refused(client, auth_headers):
    """Two providers and no more — INC-16 is in this same batch."""
    resp = await client.patch(
        _PATH, json={"provider": "route53", "api_token": "x"}, headers=auth_headers
    )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_a_viewer_cannot_write_the_provider(client, viewer_headers):
    """The settings read is open to any authenticated user; this write is not — what it
    stores is a credential that can publish records in the install's DNS zone."""
    resp = await client.patch(
        _PATH, json={"provider": "cloudflare", "api_token": "x"}, headers=viewer_headers
    )

    assert resp.status_code == 403
