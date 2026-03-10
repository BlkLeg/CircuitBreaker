"""Shared validation for file uploads: magic-byte checks and image sanity.

Use to reject content that does not match the declared or inferred type.
"""

# MIME -> list of leading-byte signatures (any match passes)
MAGIC_BYTES: dict[str, list[bytes]] = {
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/jpg": [b"\xff\xd8\xff"],
    "image/gif": [b"GIF87a", b"GIF89a"],
    "image/webp": [b"RIFF"],  # RIFF....WEBP; caller must check bytes 8:12 == b"WEBP"
    "image/x-icon": [b"\x00\x00\x01\x00", b"\x00\x00\x02\x00"],  # ICO
    "image/vnd.microsoft.icon": [b"\x00\x00\x01\x00", b"\x00\x00\x02\x00"],
}

# Extension -> MIME for branding/docs uploads
SUFFIX_TO_MIME: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
}


def verify_image_magic_bytes(
    data: bytes, content_type: str | None, *, allow_svg: bool = False
) -> bool:
    """Return True if the file's leading bytes match the given MIME type.

    content_type can be image/png, image/jpeg, image/gif, image/webp, image/x-icon (or .ico).
    If content_type is None, infer from magic bytes (optional). If allow_svg is True and
    content_type indicates SVG, return True without binary check (SVG is text).
    """
    if not data:
        return False
    ct = (content_type or "").strip().lower()
    if allow_svg and ("svg" in ct or ct == "image/svg+xml"):
        return True
    signatures = MAGIC_BYTES.get(ct) or MAGIC_BYTES.get(ct.split(";")[0].strip())
    if not signatures:
        return False
    for sig in signatures:
        if data[: len(sig)] == sig:
            if ct in ("image/webp", "image/webp ") and len(data) >= 12 and data[8:12] != b"WEBP":
                return False
            return True
    return False


def infer_image_type_from_magic(data: bytes) -> str | None:
    """Return a MIME type if the leading bytes match a known image signature."""
    if not data:
        return None
    for mime, sigs in MAGIC_BYTES.items():
        for sig in sigs:
            if data[: len(sig)] == sig:
                if mime == "image/webp" and (len(data) < 12 or data[8:12] != b"WEBP"):
                    continue
                return mime
    return None
