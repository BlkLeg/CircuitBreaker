"""Tests for the profile photo upload endpoint (PUT /api/v1/auth/me/avatar)."""

import io

import pytest

# ---------------------------------------------------------------------------
# Minimal valid 1×1 PNG
# ---------------------------------------------------------------------------
MINIMAL_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc````"
    b"\x00\x00\x00\x05\x00\x01\xa5\xf6E@\x00\x00\x00\x00IEND\xaeB`\x82"
)

_UPLOAD_URL = "/api/v1/auth/me/avatar"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _png_upload_files(filename: str = "avatar.png", data: bytes = MINIMAL_PNG):
    return {"profile_photo": (filename, io.BytesIO(data), "image/png")}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_png_upload_accepted(client, auth_headers):
    """A well-formed PNG file should be accepted with a 200 or 201 status."""
    resp = await client.put(
        _UPLOAD_URL,
        files=_png_upload_files(),
        headers=auth_headers,
    )
    assert resp.status_code in (200, 201), (
        f"Expected 200/201 for valid PNG, got {resp.status_code}: {resp.text}"
    )


@pytest.mark.asyncio
async def test_path_traversal_filename_rejected(client, auth_headers):
    """A filename containing path traversal sequences must be rejected (400/422)."""
    resp = await client.put(
        _UPLOAD_URL,
        files=_png_upload_files(filename="../../etc/passwd.jpg"),
        headers=auth_headers,
    )
    assert resp.status_code in (400, 422), (
        f"Expected 400/422 for path-traversal filename, got {resp.status_code}: {resp.text}"
    )


@pytest.mark.asyncio
async def test_exe_bytes_disguised_as_jpg_rejected(client, auth_headers):
    """An MZ-header (Windows PE) file submitted as a JPEG must be rejected (422)."""
    exe_bytes = b"MZ\x90\x00" + b"\x00" * 100

    resp = await client.put(
        _UPLOAD_URL,
        files={"profile_photo": ("evil.jpg", io.BytesIO(exe_bytes), "image/jpeg")},
        headers=auth_headers,
    )
    assert resp.status_code == 422, (
        f"Expected 422 for exe bytes disguised as jpg, got {resp.status_code}: {resp.text}"
    )


@pytest.mark.asyncio
async def test_file_too_large_rejected(client, auth_headers):
    """Files exceeding 5 MB must be rejected with 413."""
    large_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * (5 * 1024 * 1024 + 1)

    resp = await client.put(
        _UPLOAD_URL,
        files={"profile_photo": ("big.png", io.BytesIO(large_data), "image/png")},
        headers=auth_headers,
    )
    assert resp.status_code == 413, (
        f"Expected 413 for oversized file, got {resp.status_code}: {resp.text}"
    )


@pytest.mark.asyncio
async def test_upload_requires_auth(client):
    """Uploading without an auth token must return 401."""
    resp = await client.put(
        _UPLOAD_URL,
        files=_png_upload_files(),
    )
    assert resp.status_code == 401, (
        f"Expected 401 without auth, got {resp.status_code}: {resp.text}"
    )
