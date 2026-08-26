"""`service.url` renders into an anchor href, so its scheme is a security boundary.

A service created with `url: "javascript:fetch('/api/v1/admin/users')..."` stored the
string verbatim and `ServiceDetail.jsx` rendered it into `<a href={service.url}>`. Any
user who opened that service ran the payload with the viewer's session — an editor
could escalate through an admin who merely looked at the row.

This is the write half. `utils/validation.safeHref` is the read half, and it is the one
that protects rows written before this validator existed; neither replaces the other.
"""

from __future__ import annotations

import pytest

_DANGEROUS = [
    "javascript:alert(document.cookie)",
    "JaVaScRiPt:alert(1)",
    "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
    "vbscript:msgbox(1)",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("url", _DANGEROUS)
async def test_creating_a_service_rejects_an_unsafe_url_scheme(client, auth_headers, url):
    resp = await client.post(
        "/api/v1/services", json={"name": "xss-probe", "url": url}, headers=auth_headers
    )

    assert resp.status_code == 422, f"{url!r} was accepted with {resp.status_code}"


@pytest.mark.asyncio
@pytest.mark.parametrize("url", _DANGEROUS)
async def test_updating_a_service_rejects_an_unsafe_url_scheme(client, auth_headers, url):
    created = await client.post(
        "/api/v1/services",
        json={"name": f"update-probe-{abs(hash(url))}", "url": "https://example.test"},
        headers=auth_headers,
    )
    assert created.status_code in (200, 201), created.text
    service_id = created.json()["id"]

    resp = await client.patch(
        f"/api/v1/services/{service_id}", json={"url": url}, headers=auth_headers
    )

    assert resp.status_code == 422, f"{url!r} was accepted on update with {resp.status_code}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url", ["http://nas.lan:8080", "https://grafana.example.test/d/abc", None, ""]
)
async def test_ordinary_service_urls_still_pass(client, auth_headers, url):
    """The gate must not have been tightened into a wall.

    Empty and absent are how the field is left unset, and both must keep working.
    """
    resp = await client.post(
        "/api/v1/services",
        json={"name": f"ok-probe-{url!r}", "url": url},
        headers=auth_headers,
    )

    assert resp.status_code in (200, 201), f"{url!r} was rejected: {resp.text}"
