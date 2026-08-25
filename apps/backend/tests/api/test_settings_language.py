"""The settings API advertised six languages the build cannot deliver.

INC-09. The `language` field itself is kept -- it is persisted on AppSettings and User and
threaded through bootstrap, user creation and the auth service -- but the update schema
stops accepting values the product has no content for.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_language_accepts_english(client, auth_headers):
    resp = await client.put("/api/v1/settings", json={"language": "en"}, headers=auth_headers)

    assert resp.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("lang", ["es", "fr", "de", "zh", "ja"])
async def test_language_rejects_unshipped_languages(client, auth_headers, lang):
    resp = await client.put("/api/v1/settings", json={"language": lang}, headers=auth_headers)

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_settings_no_longer_advertises_show_experimental_features(client, auth_headers):
    """INC-18: on the model and in the schema, with its own migration, read by nothing.

    The register recorded it as "exposed but never read". It was worse than that — Settings
    → Advanced rendered a toggle for it, so an operator could switch on "Experimental
    Features" and nothing anywhere would consult the answer.
    """
    resp = await client.get("/api/v1/settings", headers=auth_headers)

    assert resp.status_code == 200
    assert "show_experimental_features" not in resp.json()


@pytest.mark.asyncio
async def test_the_update_schema_no_longer_names_it(client, auth_headers, db_session):
    """A PUT that still sends it is ignored as any unknown key is, and — the part that
    matters — the stored column is not moved by it. The field is simply not part of the
    API any more; OpenAPI no longer lists it either."""
    from app.db.models import AppSettings
    from app.schemas.settings import AppSettingsUpdate

    assert "show_experimental_features" not in AppSettingsUpdate.model_fields

    before = db_session.get(AppSettings, 1).show_experimental_features
    resp = await client.put(
        "/api/v1/settings", json={"show_experimental_features": not before}, headers=auth_headers
    )

    assert resp.status_code == 200
    db_session.expire_all()
    assert db_session.get(AppSettings, 1).show_experimental_features == before
