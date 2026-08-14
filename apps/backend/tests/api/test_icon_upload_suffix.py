"""An uploaded icon is stored under a suffix derived from its verified bytes.

SEC-15 rejects active content by magic byte, but the stored filename used to
come from the client: a real PNG named `evil.html` passed the magic-byte check
and was then written — and served — as `.html`. That left the serving
middleware as the only remaining layer, and `.pdf` was not in its override list
at all. The suffix now comes from the content type the bytes were validated
against, so the client's filename cannot influence what lands on disk.
"""

import pytest

pytestmark = pytest.mark.asyncio

_UPLOAD_URL = "/api/v1/compute-units/icons/upload"
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


async def _upload(client, auth_headers, filename, content_type=None, data=_PNG):
    return await client.post(
        _UPLOAD_URL,
        headers=auth_headers,
        files={"file": (filename, data, content_type or "image/png")},
        data={"name": "test-icon", "category": "custom"},
    )


@pytest.mark.parametrize("filename", ["evil.html", "evil.pdf", "evil.svg", "evil.php", "noext"])
async def test_stored_slug_ignores_the_client_filename_suffix(client, auth_headers, filename):
    resp = await _upload(client, auth_headers, filename)
    assert resp.status_code in (200, 201), resp.text

    slug = resp.json()["slug"]
    assert slug.endswith(".png"), f"{filename} was stored as {slug}"


async def test_stored_slug_follows_the_declared_type_for_each_allowed_format(client, auth_headers):
    cases = [
        ("image/png", _PNG, ".png"),
        ("image/jpeg", b"\xff\xd8\xff" + b"\x00" * 64, ".jpg"),
        ("image/webp", b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 64, ".webp"),
    ]
    for content_type, data, expected in cases:
        resp = await _upload(client, auth_headers, "upload.bin", content_type, data)
        assert resp.status_code in (200, 201), f"{content_type}: {resp.text}"
        assert resp.json()["slug"].endswith(expected), content_type


async def test_content_that_does_not_match_its_declared_type_is_still_rejected(
    client, auth_headers
):
    """The suffix change must not have loosened the magic-byte gate."""
    resp = await _upload(client, auth_headers, "x.png", "image/png", b"<html>nope</html>")
    assert resp.status_code == 415, resp.text
