"""The ACME challenge path must be readable by the CA before any certificate exists.

The plain image has no nginx, so the application serves the same webroot nginx serves in the
mono image. One directory, two servers, one mechanism.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_challenge_token_is_served_unauthenticated(client, tmp_path, monkeypatch):
    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path))
    challenge_dir = tmp_path / "acme-challenge" / ".well-known" / "acme-challenge"
    challenge_dir.mkdir(parents=True)
    (challenge_dir / "tok123").write_text("tok123.keyauth", encoding="utf-8")

    resp = await client.get("/.well-known/acme-challenge/tok123")

    assert resp.status_code == 200
    assert resp.text.strip() == "tok123.keyauth"


@pytest.mark.asyncio
async def test_unknown_token_is_404_not_the_spa(client, tmp_path, monkeypatch):
    """The SPA fallback matches every GET path; it must not answer here with index.html."""
    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path))

    resp = await client.get("/.well-known/acme-challenge/nope")

    assert resp.status_code == 404
    assert "<!doctype html" not in resp.text.lower()


@pytest.mark.asyncio
async def test_traversal_out_of_the_webroot_is_refused(client, tmp_path, monkeypatch):
    """The token is attacker-chosen text in a URL; it must never escape the webroot."""
    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path))
    (tmp_path / "acme-challenge" / ".well-known" / "acme-challenge").mkdir(parents=True)
    (tmp_path / "secret.txt").write_text("not for the CA", encoding="utf-8")

    # Percent-encoded so httpx does not normalise the traversal away before it is sent:
    # the dots have to reach the mount for this to test the mount.
    resp = await client.get("/.well-known/acme-challenge/%2e%2e%2f%2e%2e%2fsecret.txt")

    assert resp.status_code == 404
    assert "not for the CA" not in resp.text
