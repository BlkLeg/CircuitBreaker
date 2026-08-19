"""The explicit supported-image-format boundary (AGT-10).

Uploads are decoded with Pillow. AVIF is deliberately excluded rather than
supported: no product feature requires it, and its plugin is what crashed the
ARM64 package at startup.

Keeping the allowlist here — rather than letting it be whatever Pillow happens
to have compiled in — means the supported set is identical on every
architecture. Before this, `_process_avatar` took `probe.format` and re-saved in
that same format, so the accepted set silently tracked the build options of
whatever Pillow wheel was installed, and differed between amd64 and arm64.
"""

from __future__ import annotations

# Pillow format name -> the MIME type we serve it as. This mapping IS the
# supported set: auth_service's _ALLOWED_TYPES and _PILLOW_FORMAT_TO_MIME both
# derive from it, so the magic-byte allowlist, the Pillow-format allowlist and
# the served content type cannot drift apart. They were three separate literals
# that happened to agree.
PILLOW_FORMAT_TO_MIME: dict[str, str] = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "GIF": "image/gif",
    "WEBP": "image/webp",
}

SUPPORTED_UPLOAD_FORMATS = frozenset(PILLOW_FORMAT_TO_MIME)
SUPPORTED_UPLOAD_MIME_TYPES = frozenset(PILLOW_FORMAT_TO_MIME.values())


class UnsupportedImageFormat(ValueError):
    """Raised when an upload decodes to a format outside the supported set."""


def is_supported_upload_format(fmt: str | None) -> bool:
    return bool(fmt) and fmt.upper() in SUPPORTED_UPLOAD_FORMATS


def ensure_supported_upload_format(fmt: str | None) -> str:
    """Return the normalised format name, or raise UnsupportedImageFormat.

    The message names both the rejected format and the accepted set, so an
    operator can act on it without reading this file.
    """
    if not is_supported_upload_format(fmt):
        supported = ", ".join(sorted(SUPPORTED_UPLOAD_FORMATS))
        raise UnsupportedImageFormat(
            f"Unsupported image format: {fmt or 'unrecognised'}. Supported formats: {supported}."
        )
    assert fmt is not None  # narrowed by is_supported_upload_format
    return fmt.upper()
