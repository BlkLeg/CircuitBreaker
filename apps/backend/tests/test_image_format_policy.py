"""AGT-10: the supported image-format boundary must be explicit and asserted.

The reported ARM64 startup crash was a Pillow AVIF plugin failure. Nothing in
the tree excluded AVIF, replaced it, or would notice if it came back — and
_process_avatar accepted whatever Pillow could decode, re-saving in the
detected format, so AVIF was live wherever the plugin was compiled in.

This pins the formats the product claims to handle and proves they round-trip
on whichever architecture the suite runs on, so the arm64 CI job proves the
arm64 claim rather than a comment asserting it.
"""

from __future__ import annotations

import io
import platform

import pytest
from PIL import Image

from app.core.image_policy import (
    SUPPORTED_UPLOAD_FORMATS,
    UnsupportedImageFormat,
    ensure_supported_upload_format,
    is_supported_upload_format,
)


def test_supported_formats_are_declared_explicitly() -> None:
    assert SUPPORTED_UPLOAD_FORMATS == frozenset({"PNG", "JPEG", "GIF", "WEBP"})


def test_avif_is_not_a_supported_upload_format() -> None:
    # AGT-10 permits repair, exclusion, or compatible replacement. This codebase
    # excludes it: no user-facing feature needs AVIF, and the plugin is what
    # crashed on ARM64.
    assert not is_supported_upload_format("AVIF")


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "GIF", "WEBP"])
def test_every_supported_format_round_trips_on_this_architecture(fmt: str) -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(buffer, format=fmt)
    buffer.seek(0)
    with Image.open(buffer) as decoded:
        assert decoded.format == fmt
        decoded.load()


def test_format_check_is_case_insensitive_and_null_safe() -> None:
    assert is_supported_upload_format("png")
    assert is_supported_upload_format("Jpeg")
    assert not is_supported_upload_format(None)
    assert not is_supported_upload_format("")


def test_ensure_raises_for_an_unsupported_format() -> None:
    with pytest.raises(UnsupportedImageFormat) as excinfo:
        ensure_supported_upload_format("AVIF")
    # The operator has to be able to act on this without reading the source.
    assert "AVIF" in str(excinfo.value)
    assert "PNG" in str(excinfo.value)


def test_ensure_returns_the_normalised_format_when_supported() -> None:
    assert ensure_supported_upload_format("png") == "PNG"


def test_pillow_imports_without_the_avif_plugin_crashing() -> None:
    """The AGT-10 crash was at import/plugin-registration time, not decode time."""
    from PIL import features

    features.check("avif")  # must not raise, whether or not the codec is present
    assert platform.machine()  # records the architecture this ran on


def test_mime_mapping_covers_exactly_the_supported_formats() -> None:
    from app.core.image_policy import (
        PILLOW_FORMAT_TO_MIME,
        SUPPORTED_UPLOAD_MIME_TYPES,
    )

    assert set(PILLOW_FORMAT_TO_MIME) == set(SUPPORTED_UPLOAD_FORMATS)
    assert set(PILLOW_FORMAT_TO_MIME.values()) == set(SUPPORTED_UPLOAD_MIME_TYPES)


def test_auth_service_allowlists_derive_from_the_policy() -> None:
    """AGT-10: the magic-byte allowlist, the Pillow-format allowlist and the
    served content type were three separate literals that happened to agree. A
    fifth format added to one and not the others would open a gap silently."""
    from app.core.image_policy import PILLOW_FORMAT_TO_MIME, SUPPORTED_UPLOAD_MIME_TYPES
    from app.services import auth_service

    assert auth_service._ALLOWED_TYPES == set(SUPPORTED_UPLOAD_MIME_TYPES)
    assert auth_service._PILLOW_FORMAT_TO_MIME == PILLOW_FORMAT_TO_MIME


def test_avatar_processing_rejects_an_unsupported_decoded_format() -> None:
    """Defence in depth behind the magic-byte check: even if a format sniffs as
    allowed, the decoded format must still be in the policy."""
    from app.core.image_policy import UnsupportedImageFormat
    from app.services.auth_service import _process_avatar

    # BMP decodes fine in Pillow but is outside the supported set.
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(buffer, format="BMP")
    with pytest.raises(UnsupportedImageFormat):
        _process_avatar(buffer.getvalue())


def test_avatar_processing_accepts_a_supported_format() -> None:
    from app.services.auth_service import _process_avatar

    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), (9, 9, 9)).save(buffer, format="PNG")
    processed, fmt = _process_avatar(buffer.getvalue())
    assert fmt == "PNG"
    assert processed
