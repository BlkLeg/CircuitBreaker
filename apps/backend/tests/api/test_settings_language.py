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
