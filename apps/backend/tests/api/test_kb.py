"""Integration tests for the /api/v1/kb endpoints."""

from __future__ import annotations

import pytest

from app.db.models import KbHostname, KbOui


@pytest.fixture
def kb_entry(db_session):
    """Seed one learned KbOui row for tests that need an existing entry."""
    entry = KbOui(
        prefix="001122",
        vendor="Acme Devices Inc.",
        device_type="server",
        source="learned",
    )
    db_session.add(entry)
    db_session.flush()
    return entry


# ── list ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_oui_returns_entries(client, auth_headers, kb_entry):
    resp = await client.get("/api/v1/kb/oui", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert any(e["prefix"] == "001122" for e in data)


@pytest.mark.asyncio
async def test_list_oui_filter_by_source(client, auth_headers, kb_entry):
    resp = await client.get("/api/v1/kb/oui?source=learned", headers=auth_headers)
    assert resp.status_code == 200
    assert all(e["source"] == "learned" for e in resp.json())


@pytest.mark.asyncio
async def test_list_oui_requires_admin(client, viewer_headers):
    resp = await client.get("/api/v1/kb/oui", headers=viewer_headers)
    assert resp.status_code == 403


# ── create ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_oui(client, auth_headers):
    resp = await client.post(
        "/api/v1/kb/oui",
        json={"prefix": "AABBCC", "vendor": "Test Vendor", "device_type": "router"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["prefix"] == "AABBCC"
    assert body["vendor"] == "Test Vendor"
    assert body["source"] == "manual"


@pytest.mark.asyncio
async def test_create_oui_invalid_prefix(client, auth_headers):
    resp = await client.post(
        "/api/v1/kb/oui",
        json={"prefix": "ZZZZZZ", "vendor": "Bad Prefix"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_oui_duplicate_returns_409(client, auth_headers, kb_entry):
    resp = await client.post(
        "/api/v1/kb/oui",
        json={"prefix": "001122", "vendor": "Duplicate"},
        headers=auth_headers,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_create_oui_requires_admin(client, viewer_headers):
    resp = await client.post(
        "/api/v1/kb/oui",
        json={"prefix": "AABBCC", "vendor": "Test"},
        headers=viewer_headers,
    )
    assert resp.status_code == 403


# ── update ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_oui(client, auth_headers, kb_entry):
    resp = await client.put(
        "/api/v1/kb/oui/001122",
        json={"vendor": "Updated Vendor", "device_type": "switch"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["vendor"] == "Updated Vendor"
    assert body["device_type"] == "switch"


@pytest.mark.asyncio
async def test_update_oui_not_found(client, auth_headers):
    resp = await client.put(
        "/api/v1/kb/oui/FFFFFF",
        json={"vendor": "Nobody"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


# ── delete ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_oui(client, auth_headers, kb_entry):
    resp = await client.delete("/api/v1/kb/oui/001122", headers=auth_headers)
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_oui_not_found(client, auth_headers):
    resp = await client.delete("/api/v1/kb/oui/FFFFFF", headers=auth_headers)
    assert resp.status_code == 404


# ── export ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_export_oui_format(client, auth_headers, kb_entry):
    resp = await client.get("/api/v1/kb/oui/export", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "mac_oui_prefixes" in body
    assert "001122" in body["mac_oui_prefixes"]
    assert body["mac_oui_prefixes"]["001122"]["vendor"] == "Acme Devices Inc."


# ═══════════════════════════════════════════════════════════════════════════════
# Hostname KB endpoints
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def kb_hostname_entry(db_session):
    """Seed one learned KbHostname row for tests that need an existing entry."""
    entry = KbHostname(
        pattern="pve",
        match_type="prefix",
        vendor="Proxmox Server Solutions GmbH",
        device_type="hypervisor",
        os_family="Linux",
        source="learned",
    )
    db_session.add(entry)
    db_session.flush()
    return entry


# ── list ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_hostname_returns_entries(client, auth_headers, kb_hostname_entry):
    resp = await client.get("/api/v1/kb/hostname", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert any(e["pattern"] == "pve" for e in data)


@pytest.mark.asyncio
async def test_list_hostname_filter_by_source(client, auth_headers, kb_hostname_entry):
    resp = await client.get("/api/v1/kb/hostname?source=learned", headers=auth_headers)
    assert resp.status_code == 200
    assert all(e["source"] == "learned" for e in resp.json())


@pytest.mark.asyncio
async def test_list_hostname_requires_admin(client, viewer_headers):
    resp = await client.get("/api/v1/kb/hostname", headers=viewer_headers)
    assert resp.status_code == 403


# ── create ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_hostname(client, auth_headers):
    resp = await client.post(
        "/api/v1/kb/hostname",
        json={
            "pattern": "opnsense",
            "match_type": "exact",
            "vendor": "OPNsense",
            "device_type": "firewall",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["pattern"] == "opnsense"
    assert body["match_type"] == "exact"
    assert body["vendor"] == "OPNsense"
    assert body["source"] == "manual"


@pytest.mark.asyncio
async def test_create_hostname_invalid_match_type(client, auth_headers):
    resp = await client.post(
        "/api/v1/kb/hostname",
        json={"pattern": "test", "match_type": "invalid"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_hostname_duplicate_returns_409(client, auth_headers, kb_hostname_entry):
    resp = await client.post(
        "/api/v1/kb/hostname",
        json={"pattern": "pve", "match_type": "prefix"},
        headers=auth_headers,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_create_hostname_requires_admin(client, viewer_headers):
    resp = await client.post(
        "/api/v1/kb/hostname",
        json={"pattern": "test"},
        headers=viewer_headers,
    )
    assert resp.status_code == 403


# ── update ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_hostname(client, auth_headers, kb_hostname_entry):
    entry_id = kb_hostname_entry.id
    resp = await client.put(
        f"/api/v1/kb/hostname/{entry_id}",
        json={"vendor": "Proxmox Updated", "match_type": "contains"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["vendor"] == "Proxmox Updated"
    assert body["match_type"] == "contains"


@pytest.mark.asyncio
async def test_update_hostname_not_found(client, auth_headers):
    resp = await client.put(
        "/api/v1/kb/hostname/999999",
        json={"vendor": "Nobody"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


# ── delete ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_hostname(client, auth_headers, kb_hostname_entry):
    resp = await client.delete(f"/api/v1/kb/hostname/{kb_hostname_entry.id}", headers=auth_headers)
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_hostname_not_found(client, auth_headers):
    resp = await client.delete("/api/v1/kb/hostname/999999", headers=auth_headers)
    assert resp.status_code == 404


# ── export ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_export_hostname_format(client, auth_headers, kb_hostname_entry):
    resp = await client.get("/api/v1/kb/hostname/export", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "hostname_patterns" in body
    patterns = body["hostname_patterns"]
    assert any(p["pattern"] == "pve" for p in patterns)
    match = next(p for p in patterns if p["pattern"] == "pve")
    assert match["vendor"] == "Proxmox Server Solutions GmbH"
    assert match["match_type"] == "prefix"
