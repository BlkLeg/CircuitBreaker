"""Integration tests for the /api/v1/docs import surface.

The import endpoint accepts an attacker-supplied ZIP and, before this file
existed, had no tests at all. What it needs pinned is not the happy path (a
handful of small .md files land as docs) so much as the resource ceilings: a
ZIP is ten megabytes of *compressed* input at most, and deflate happily turns
ten megabytes into ten gigabytes. Every test below that asserts a 413 is
asserting that the ceiling is enforced from the ZIP's own metadata, i.e.
*before* the bytes are spent, rather than after.
"""

from __future__ import annotations

import binascii
import io
import struct
import tracemalloc
import zipfile

import pytest
from fastapi import HTTPException

from app.api.docs import _parse_zip_entries
from app.services.docs_service import (
    MAX_IMPORT_MD_BYTES,
    MAX_IMPORT_TOTAL_MD_BYTES,
    MAX_IMPORT_ZIP_ENTRIES,
)

# 64 MB of a single repeated byte deflates to roughly 64 KB, so this comfortably
# clears the 10 MB compressed-payload gate while declaring an uncompressed size
# 64x over the 1 MB per-member cap. Large enough that decompressing it is
# unmistakable in a tracemalloc peak, small enough that building it in a test
# process is cheap.
_BOMB_UNCOMPRESSED_BYTES = 64 * 1024 * 1024

# Headroom over the ~1 MB a correct implementation is allowed to hold (the
# bounded read of MAX_IMPORT_MD_BYTES + 1) plus whatever the ASGI stack and
# the ZIP payload itself cost. Anything under this is decisively "did not
# decompress 64 MB"; the failing behavior peaks two orders of magnitude higher.
_PEAK_ALLOCATION_CEILING = 12 * 1024 * 1024


def _zip_of(members: dict[str, bytes]) -> bytes:
    """Build an in-memory ZIP_DEFLATED archive from {filename: contents}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name, contents in members.items():
            zf.writestr(name, contents)
    return buf.getvalue()


# ── the bomb ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_deflate_bomb_is_rejected_without_being_decompressed_into_memory(
    client, auth_headers
):
    """A member declaring 64 MB must be refused on its declared size alone.

    Reading first and measuring afterwards produces the right status code by
    accident while having already allocated the whole 64 MB, so the status
    assertion on its own proves nothing here — the peak allocation is the
    actual subject of the test.
    """
    payload = _zip_of({"bomb.md": b"A" * _BOMB_UNCOMPRESSED_BYTES})
    # Sanity-check the premise: this has to get past the compressed-size gate,
    # otherwise the test would pass for entirely the wrong reason.
    assert len(payload) < 10 * 1024 * 1024

    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        resp = await client.post(
            "/api/v1/docs/import",
            files={"file": ("bomb.zip", payload, "application/zip")},
            headers=auth_headers,
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert resp.status_code == 413
    assert peak < _PEAK_ALLOCATION_CEILING, (
        f"import allocated {peak / 1024 / 1024:.1f} MB handling a 64 MB deflate bomb; "
        "the member was decompressed before its size was checked"
    )


def _zip_understating_its_member_size(body: bytes, declared: int) -> bytes:
    """Build a ZIP whose member header claims `declared` bytes but really holds
    `body`, with the CRC-32 rewritten to match the truncated prefix so the read
    completes instead of aborting on a checksum mismatch.

    This is the shape a file_size-only defense misses. `ZipFile.read` hands the
    decompressor a one-gigabyte max_length and truncates to file_size only
    afterwards, so this archive costs the full uncompressed size in memory while
    handing back `declared` bytes and never tripping a size check at all.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.writestr("liar.md", body)
    raw = bytearray(buf.getvalue())

    crc = binascii.crc32(body[:declared]) & 0xFFFFFFFF
    local = raw.find(b"PK\x03\x04")
    central = raw.find(b"PK\x01\x02")
    # Uncompressed size and CRC-32 live at fixed offsets in each record: 22/14
    # in the local file header, 24/16 in the central directory entry.
    struct.pack_into("<I", raw, local + 22, declared)
    struct.pack_into("<I", raw, local + 14, crc)
    struct.pack_into("<I", raw, central + 24, declared)
    struct.pack_into("<I", raw, central + 16, crc)
    return bytes(raw)


def test_a_member_understating_its_own_size_is_still_read_under_a_bound():
    """The declared size is attacker-controlled in the cheap direction too.

    A header claiming a hundred bytes over a 64 MB deflate stream satisfies any
    check made against info.file_size, so the bound that matters is the one on
    the read itself.
    """
    payload = _zip_understating_its_member_size(b"A" * _BOMB_UNCOMPRESSED_BYTES, 100)

    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        entries = _parse_zip_entries(payload)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert entries == [("liar", "A" * 100)]
    assert peak < _PEAK_ALLOCATION_CEILING, (
        f"parsing allocated {peak / 1024 / 1024:.1f} MB for a member declaring 100 bytes; "
        "the member was decompressed in full despite the declared size"
    )


# ── the aggregate ceilings ───────────────────────────────────────────────────


def test_a_zip_whose_members_total_more_than_the_uncompressed_budget_is_rejected():
    """Per-member caps do not bound the archive: sum them and enforce that too.

    Twenty-five members of one megabyte each individually satisfy the 1 MB
    per-.md cap, so nothing short of an aggregate budget stops a 10 MB ZIP from
    expanding into hundreds of megabytes of docs.
    """
    member = b"A" * MAX_IMPORT_MD_BYTES
    member_count = 25
    assert member_count * MAX_IMPORT_MD_BYTES > MAX_IMPORT_TOTAL_MD_BYTES
    payload = _zip_of({f"doc-{i}.md": member for i in range(member_count)})

    with pytest.raises(HTTPException) as exc_info:
        _parse_zip_entries(payload)

    assert exc_info.value.status_code == 413
    assert "20 MB" in exc_info.value.detail


def test_a_zip_with_more_members_than_the_entry_cap_is_rejected():
    """Member count is its own resource dimension — each entry becomes a row.

    Tiny members sail past every byte-oriented limit, so an archive of a
    hundred thousand one-byte .md files is a cheap way to make the importer do
    a hundred thousand INSERTs.
    """
    payload = _zip_of({f"doc-{i}.md": b"x" for i in range(MAX_IMPORT_ZIP_ENTRIES + 1)})

    with pytest.raises(HTTPException) as exc_info:
        _parse_zip_entries(payload)

    assert exc_info.value.status_code == 413
    assert "500" in exc_info.value.detail


def test_a_zip_sitting_exactly_on_the_entry_cap_is_accepted():
    """The cap is inclusive — 500 members is fine, 501 is not."""
    entries = _parse_zip_entries(
        _zip_of({f"doc-{i}.md": b"x" for i in range(MAX_IMPORT_ZIP_ENTRIES)})
    )
    assert len(entries) == MAX_IMPORT_ZIP_ENTRIES


# ── the paths that must keep working ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_small_well_formed_zip_still_imports_its_markdown(client, auth_headers):
    payload = _zip_of(
        {
            "notes/runbook.md": b"# Runbook\n\nRestart the thing.\n",
            "notes/README.txt": b"not markdown, must be skipped",
        }
    )

    resp = await client.post(
        "/api/v1/docs/import",
        files={"file": ("docs.zip", payload, "application/zip")},
        headers=auth_headers,
    )

    assert resp.status_code == 201
    body = resp.json()
    # Path traversal defense keeps only the bare filename, so the title is the
    # stem of "runbook.md", not anything derived from the "notes/" prefix.
    assert [d["title"] for d in body] == ["runbook"]
    assert "Restart the thing." in body[0]["body_md"]


def test_a_member_one_byte_over_the_per_file_cap_is_rejected():
    payload = _zip_of({"big.md": b"A" * (MAX_IMPORT_MD_BYTES + 1)})

    with pytest.raises(HTTPException) as exc_info:
        _parse_zip_entries(payload)

    assert exc_info.value.status_code == 413
    assert "big.md exceeds 1 MB limit" == exc_info.value.detail
