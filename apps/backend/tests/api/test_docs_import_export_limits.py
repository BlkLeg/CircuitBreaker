"""The docs import/export surface, at the edges where it meets hostile input.

`test_docs.py` next door pins the resource ceilings the B05 fix introduced.
This file pins the three things that fix left behind:

* **B38** — the ceilings are enforced by `_parse_zip_entries`/`_parse_md_entry`
  on a `bytes` the handler has *already* materialised with a bare
  `await file.read()`. A 10 MB gate reached after an unbounded read is a gate
  reached after the cost it exists to prevent.
* **B41** — only the `ZipFile()` constructor was wrapped, and only against
  `BadZipFile`, so an archive whose *members* are corrupt — and some whose
  directory is — raised out of the handler as a 500 rather than the 400 the
  same archive gets when it is unreadable in a way zipfile happens to have a
  named exception for.
* **R10** — `export_docs_zip` grew no notion of the caps `_parse_zip_entries`
  did, so a large install produced an archive its own importer answered with
  413 and said nothing about it.

Two things these tests are deliberately *not*:

They do not assert that two constants are equal, and they do not assert the
argument a handler passes to `read()`. Equal constants prove the numbers match
today; the argument to `read()` pins one particular shape of a correct answer.
Both were how earlier versions of these tests managed to pass without pinning
anything. What is asserted instead is observable: how many body bytes a handler
can be made to pull into the process, and what the *other end* of the archive
does with what this end produced — the R10 tests move a ceiling and require
both ends to move with it, which is the property "one shared definition" is
supposed to buy and which two agreeing literals would fail.
"""

from __future__ import annotations

import io
import random
import struct
import zipfile

import pytest
from fastapi import HTTPException

from app.api.docs import _parse_zip_entries, import_docs, upload_doc_image
from app.db.models import Doc
from app.services import docs_service
from app.services.docs_service import (
    MAX_IMPORT_MD_BYTES,
    MAX_IMPORT_ZIP_BYTES,
)

_MAX_IMAGE_BYTES = 5 * 1024 * 1024


# ── B38: the read that happens before the gate ───────────────────────────────


class _RecordingUpload:
    """Stand-in for Starlette's UploadFile that records what it handed over.

    The defect is not visible in the response — an unbounded read and a bounded
    one both end in the same 413 — so the subject of these two tests is the
    total number of body bytes the handler pulled into the process before it
    answered. That is the quantity B38 is about, and it is implementation-
    agnostic: a handler that reads once with a size, and one that loops over
    chunks until it has enough, both pass; only one that asks for everything
    fails. An earlier version of these tests asserted `read_sizes == [cap + 1]`,
    i.e. the literal argument, which a correct bounded-loop rewrite would have
    failed while being exactly as safe.
    """

    def __init__(self, filename: str, content_type: str, size: int) -> None:
        self.filename = filename
        self.content_type = content_type
        self._remaining = size
        self.bytes_served = 0

    async def read(self, size: int = -1) -> bytes:
        # -1 is the default, i.e. a bare `await file.read()`: everything left.
        n = self._remaining if size < 0 else min(size, self._remaining)
        self._remaining -= n
        self.bytes_served += n
        return b"P" * n


@pytest.mark.asyncio
async def test_the_importer_never_pulls_in_more_than_the_zip_cap_plus_one_byte():
    upload = _RecordingUpload("huge.zip", "application/zip", MAX_IMPORT_ZIP_BYTES * 2)

    with pytest.raises(HTTPException) as exc_info:
        await import_docs(file=upload, db=None, _=None)

    assert exc_info.value.status_code == 413
    # One byte past the cap is all a `len(data) > cap` gate needs to tell an
    # upload sitting exactly on the limit from one over it. Anything more than
    # that is the whole body in memory, which is B38.
    assert upload.bytes_served <= MAX_IMPORT_ZIP_BYTES + 1


@pytest.mark.asyncio
async def test_the_image_upload_never_pulls_in_more_than_the_image_cap_plus_one_byte(
    monkeypatch,
):
    monkeypatch.setattr(docs_service, "get_doc", lambda db, doc_id: {"id": doc_id})
    upload = _RecordingUpload("huge.png", "image/png", _MAX_IMAGE_BYTES * 2)

    with pytest.raises(HTTPException) as exc_info:
        await upload_doc_image(doc_id=1, file=upload, db=None, _=None)

    assert exc_info.value.status_code == 413
    assert upload.bytes_served <= _MAX_IMAGE_BYTES + 1


# ── B41: unreadable archives are the client's problem, not a 500 ─────────────

_WELLFORMED_BODY = b"# Notes\n\n" + b"hello world " * 500


def _wellformed(method: int = zipfile.ZIP_DEFLATED) -> bytearray:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", method) as zf:
        zf.writestr("notes.md", _WELLFORMED_BODY)
    return bytearray(buf.getvalue())


def _member_data_offset(raw: bytearray, local: int) -> int:
    name_len, extra_len = struct.unpack_from("<HH", raw, local + 26)
    return local + 30 + name_len + extra_len


def _shred_member(raw: bytearray) -> bytes:
    local = raw.find(b"PK\x03\x04")
    off = _member_data_offset(raw, local)
    raw[off : off + 24] = b"\xff" * 24
    return bytes(raw)


def _shredded_deflate_stream() -> bytes:
    """Garbage where the deflate stream should be — raises `zlib.error`."""
    return _shred_member(_wellformed(zipfile.ZIP_DEFLATED))


def _shredded_bzip2_stream() -> bytes:
    """The same shredding of a ZIP_BZIP2 member — a bare `OSError`.

    This is the input that refuted the first attempt at B41. Method 12 is
    standard, CPython decompresses it, and the uploader picks it with two bytes
    in the header; `bz2.BZ2Decompressor.decompress` answers a corrupt stream
    with `OSError("Invalid data stream")`, which is not `BadZipFile`, not
    `zlib.error`, and not any of the other three types the enumerated catch
    listed. It reached `POST /api/v1/docs/import` as a 500.
    """
    return _shred_member(_wellformed(zipfile.ZIP_BZIP2))


def _shredded_lzma_stream() -> bytes:
    """The same shredding of a ZIP_LZMA member.

    Lands on `BadZipFile` today, so the enumerated catch covered it — by luck,
    not by design: nothing in zipfile promises that `lzma.LZMAError` stays
    wrapped, and the corruption fuzz below produces it bare.
    """
    return _shred_member(_wellformed(zipfile.ZIP_LZMA))


def _truncated_deflate_stream() -> bytes:
    """Half the compressed stream removed — `BadZipFile: Bad CRC-32`.

    Structurally valid all the way through: the member inflates, it just
    inflates to fewer bytes than the header's checksum covers, so the error
    arrives at the *end* of the read rather than at its start. That makes it a
    different code path from the shredded case above, which dies inside zlib.
    """
    raw = _wellformed()
    local = raw.find(b"PK\x03\x04")
    off = _member_data_offset(raw, local)
    csize = struct.unpack_from("<I", raw, local + 18)[0]
    kept = csize // 2
    del raw[off + kept : off + csize]
    struct.pack_into("<I", raw, local + 18, kept)
    central = raw.find(b"PK\x01\x02")
    struct.pack_into("<I", raw, central + 20, kept)
    struct.pack_into("<I", raw, raw.find(b"PK\x05\x06") + 16, central)
    return bytes(raw)


def _bad_local_header_magic() -> bytes:
    """Central directory intact, local file header signature clobbered."""
    raw = _wellformed()
    local = raw.find(b"PK\x03\x04")
    raw[local : local + 4] = b"PK\x09\x09"
    return bytes(raw)


def _encrypted_member() -> bytes:
    """General-purpose bit 0 set — zipfile answers with a bare `RuntimeError`."""
    raw = _wellformed()
    struct.pack_into("<H", raw, raw.find(b"PK\x03\x04") + 6, 0x1)
    struct.pack_into("<H", raw, raw.find(b"PK\x01\x02") + 8, 0x1)
    return bytes(raw)


def _unsupported_compression() -> bytes:
    """A method zipfile has no decompressor for — `NotImplementedError`."""
    raw = _wellformed()
    struct.pack_into("<H", raw, raw.find(b"PK\x03\x04") + 8, 99)
    struct.pack_into("<H", raw, raw.find(b"PK\x01\x02") + 10, 99)
    return bytes(raw)


def _unsupported_directory_version() -> bytes:
    """A version byte in the *central directory* zipfile refuses to parse.

    `NotImplementedError("zip file version 12.8")`, raised by the `ZipFile()`
    constructor rather than by a member read — so it escaped the handler even
    after the member read was wrapped, because the constructor's own catch was
    still `except zipfile.BadZipFile`.
    """
    raw = _wellformed()
    struct.pack_into("<H", raw, raw.find(b"PK\x01\x02") + 6, 128)
    return bytes(raw)


@pytest.mark.parametrize(
    "build",
    [
        _shredded_deflate_stream,
        _shredded_bzip2_stream,
        _shredded_lzma_stream,
        _truncated_deflate_stream,
        _bad_local_header_magic,
        _encrypted_member,
        _unsupported_compression,
        _unsupported_directory_version,
    ],
    ids=[
        "shredded-deflate",
        "shredded-bzip2",
        "shredded-lzma",
        "truncated-crc",
        "bad-local-magic",
        "encrypted",
        "unsupported-method",
        "unsupported-directory-version",
    ],
)
def test_an_unreadable_archive_is_a_client_error_not_a_server_error(build):
    """Every one of these is "your archive is broken", and every one of them
    escaped the handler uncaught at some point in this fix's history: first
    because only the `ZipFile()` constructor was wrapped, then because the
    member read was wrapped with a five-element tuple that bzip2 walks through.
    """
    with pytest.raises(HTTPException) as exc_info:
        _parse_zip_entries(build())

    assert exc_info.value.status_code == 400


@pytest.mark.parametrize(
    "method",
    [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA],
    ids=["stored", "deflate", "bzip2", "lzma"],
)
def test_no_corruption_of_any_supported_method_escapes_as_a_server_error(method):
    """The named cases above pin the corruptions somebody thought of. This one
    pins the class, because thinking of them is what failed twice already.

    Deterministic: same seed, same 120 mutations of the same archive, every
    run. Anything that is not an HTTPException propagates and fails the test,
    which is precisely what a 500 out of the import handler is.
    """
    rng = random.Random(20260826)
    base = _wellformed(method)
    refused = 0
    for _ in range(120):
        raw = bytearray(base)
        for _ in range(rng.randint(1, 6)):
            raw[rng.randrange(len(raw))] = rng.getrandbits(8)
        try:
            _parse_zip_entries(bytes(raw))
        except HTTPException as exc:
            assert 400 <= exc.status_code < 500, f"{exc.status_code} for a corrupt archive"
            refused += 1

    # Guard against the test going quiet: if a change to the corpus or to
    # zipfile ever made these mutations harmless, the loop above would pass
    # without exercising the catch at all.
    assert refused >= 40, f"only {refused}/120 mutations were rejected; corpus went inert"


def test_a_well_formed_archive_is_still_parsed_and_the_size_gates_still_answer_413():
    """The control for the corruption tests — and a guard on the blunt catch.

    `_parse_zip_entries` answers an unreadable member with 400 by catching
    `Exception` around the two zipfile calls, which is only safe while the try
    body stays exactly those two calls. `HTTPException` is an `Exception` too,
    so a maintainer who widens that `try` to cover the size checks turns every
    B05 ceiling into a "could not read" 400 and loses the distinction between
    "your archive is broken" and "your archive is too big" — silently, because
    both are 4xx. Hence both halves here: a good archive parses, and an
    oversized one is still refused as oversized.
    """
    assert _parse_zip_entries(bytes(_wellformed()))[0][0] == "notes"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("big.md", b"A" * (MAX_IMPORT_MD_BYTES + 1))

    with pytest.raises(HTTPException) as exc_info:
        _parse_zip_entries(buf.getvalue())

    assert exc_info.value.status_code == 413


# ── R10: the two ends of the archive, and the one definition they share ──────


def _seed_docs(db, count: int, body: str = "# doc\n") -> list[int]:
    docs = [Doc(title=f"doc-{i}", body_md=body, body_html="") for i in range(count)]
    db.add_all(docs)
    db.flush()
    return [d.id for d in docs]


def _members(data: bytes) -> list[str]:
    return zipfile.ZipFile(io.BytesIO(data)).namelist()


def test_moving_one_ceiling_moves_both_ends_of_the_archive(db_session, monkeypatch):
    """R10's actual property, stated so that two agreeing literals fail it.

    The ceilings are defined once, in docs_service, and read through the module
    by both ends at call time. Move the member cap and *both* ends must be
    looking at the moved value: the exporter must notice it is over, and the
    importer must refuse the archive and name the moved number. A copy of the
    cap in api/docs.py — whether written as a literal or bound by a
    `from ... import` at module load — leaves the importer on the old value and
    fails the second half here, which is the drift R10 is.
    """
    monkeypatch.setattr(docs_service, "MAX_IMPORT_ZIP_ENTRIES", 3)
    ids = _seed_docs(db_session, 4)

    data = docs_service.export_docs_zip(db_session, ids=ids)

    assert docs_service.IMPORT_WARNING_MEMBER in _members(data)
    with pytest.raises(HTTPException) as exc_info:
        _parse_zip_entries(data)
    assert exc_info.value.status_code == 413
    assert "3 files" in exc_info.value.detail


def test_an_export_sitting_exactly_on_the_member_cap_is_accepted_by_the_importer(
    db_session, monkeypatch
):
    """The agreement at the boundary, as a round trip rather than as equal ints.

    The warning member is why this has teeth beyond being a premise check: an
    archive exactly on the member cap has no room for an extra member, so a
    warning appended unconditionally rather than only to an over-ceiling
    archive would be the thing that made a perfectly good backup unimportable.
    """
    monkeypatch.setattr(docs_service, "MAX_IMPORT_ZIP_ENTRIES", 4)
    ids = _seed_docs(db_session, 4)

    data = docs_service.export_docs_zip(db_session, ids=ids)

    assert docs_service.IMPORT_WARNING_MEMBER not in _members(data)
    assert len(_parse_zip_entries(data)) == 4


def test_a_round_trip_of_ordinary_docs_works_and_is_measured_in_the_importer_s_units(
    db_session, monkeypatch
):
    """Ordinary docs survive the round trip, and the two ends count the same.

    The second half is the same drift one layer down. The importer weighs
    `ZipInfo.file_size`, which is UTF-8 bytes; an exporter that measured
    `len(doc.body_md)` would be counting characters, agree with the importer on
    every ASCII doc, and quietly disagree on the first doc with an accented
    character in it. 40 characters that encode to 80 bytes, against a 64-byte
    ceiling, is the whole disagreement in one doc.
    """
    ids = _seed_docs(db_session, 3, body="# Runbook\n\nRestart the thing.\n")

    entries = _parse_zip_entries(docs_service.export_docs_zip(db_session, ids=ids))

    assert sorted(t for t, _ in entries) == sorted(f"{i}-doc_{n}" for n, i in enumerate(ids))
    assert all("Restart the thing." in body for _, body in entries)

    monkeypatch.setattr(docs_service, "MAX_IMPORT_MD_BYTES", 64)
    wide = _seed_docs(db_session, 1, body="é" * 40)

    data = docs_service.export_docs_zip(db_session, ids=wide)

    assert "per-member import ceiling" in _warning_text(data)
    with pytest.raises(HTTPException) as exc_info:
        _parse_zip_entries(data)
    assert exc_info.value.status_code == 413


def _warning_text(data: bytes) -> str:
    zf = zipfile.ZipFile(io.BytesIO(data))
    return zf.read(docs_service.IMPORT_WARNING_MEMBER).decode("utf-8")


def test_an_over_cap_export_still_hands_over_every_doc_and_says_what_is_wrong(
    db_session, monkeypatch
):
    """The archive is built, not refused, and it carries its own diagnosis.

    Refusing was tried and taken back: `docsApi.exportAll()` is the only caller
    in the product, it passes no `ids`, there is no subset-export UI behind it,
    and it reads the response as a Blob — so the 413's `detail` was never
    parsed and the operator saw "Request failed with status code 413". A large
    install lost docs export outright in exchange for a message it could not
    read. The .md members are good markdown either way; what is genuinely
    refused is feeding the whole thing back to /import in one piece, and that
    is what the warning member says, in the artifact the operator still has at
    restore time.
    """
    monkeypatch.setattr(docs_service, "MAX_IMPORT_ZIP_ENTRIES", 3)
    ids = _seed_docs(db_session, 4)

    data = docs_service.export_docs_zip(db_session, ids=ids)

    assert sum(1 for name in _members(data) if name.endswith(".md")) == 4
    warning = _warning_text(data)
    assert "3-member import ceiling" in warning
    assert "?ids=" in warning
    # And the warning is telling the truth: single-shot re-import is refused.
    with pytest.raises(HTTPException) as exc_info:
        _parse_zip_entries(data)
    assert exc_info.value.status_code == 413


def test_an_export_over_the_uncompressed_budget_carries_the_same_warning(db_session, monkeypatch):
    """Member count is not the only ceiling the importer enforces."""
    monkeypatch.setattr(docs_service, "MAX_IMPORT_TOTAL_MD_BYTES", 100)
    ids = _seed_docs(db_session, 4, body="A" * 40)

    data = docs_service.export_docs_zip(db_session, ids=ids)

    assert sum(1 for name in _members(data) if name.endswith(".md")) == 4
    assert "uncompressed bytes, over the 100-byte import ceiling" in _warning_text(data)


def test_an_export_of_a_doc_larger_than_the_per_member_cap_names_that_doc(db_session, monkeypatch):
    """A single oversized doc makes the whole archive unimportable too."""
    monkeypatch.setattr(docs_service, "MAX_IMPORT_MD_BYTES", 64)
    ids = _seed_docs(db_session, 1, body="A" * 100)

    warning = _warning_text(docs_service.export_docs_zip(db_session, ids=ids))

    assert f"{ids[0]}-doc_0.md is 100 bytes" in warning


@pytest.mark.asyncio
async def test_the_export_endpoint_still_serves_a_large_install_its_own_docs(
    client, auth_headers, db_session, monkeypatch
):
    """The regression guard for the availability defect the refusal introduced.

    An install past the member cap must still be able to get its docs out of
    the product by the one route the product offers.
    """
    monkeypatch.setattr(docs_service, "MAX_IMPORT_ZIP_ENTRIES", 3)
    ids = _seed_docs(db_session, 4)

    resp = await client.get(
        "/api/v1/docs/export",
        params=[("ids", i) for i in ids],
        headers=auth_headers,
    )

    assert resp.status_code == 200
    names = _members(resp.content)
    assert sum(1 for name in names if name.endswith(".md")) == 4
    assert docs_service.IMPORT_WARNING_MEMBER in names
