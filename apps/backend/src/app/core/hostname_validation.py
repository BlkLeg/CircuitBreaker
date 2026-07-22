"""FQDN validation for domain configuration (nginx server_name / cert CN).

Separate from app.core.url_validation, which validates outbound HTTP
targets against SSRF (webhooks, Proxmox) — a different concern from
"is this string a syntactically legal FQDN to become a server_name/CN".
"""

import ipaddress
import re

_LABEL_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_FORBIDDEN_EXACT = {"localhost"}
_FORBIDDEN_SUFFIX = ".localhost"


def validate_fqdn(value: str) -> str:
    """Raise ValueError if value isn't a valid FQDN suitable for
    nginx server_name / a self-signed cert CN. Returns the normalized
    (stripped, lowercased) value on success."""
    v = (value or "").strip().lower()
    if not v:
        raise ValueError("FQDN is required")
    if len(v) > 253:
        raise ValueError("FQDN must be 253 characters or fewer")
    if v in _FORBIDDEN_EXACT or v.endswith(_FORBIDDEN_SUFFIX):
        raise ValueError("FQDN must not be localhost")

    is_ip_literal = True
    try:
        ipaddress.ip_address(v)
    except ValueError:
        is_ip_literal = False
    if is_ip_literal:
        raise ValueError("FQDN must not be an IP address literal")

    labels = v.split(".")
    if len(labels) < 2 or any(label == "" for label in labels):
        raise ValueError("FQDN must contain at least one dot (e.g. host.example.com)")
    for label in labels:
        if not _LABEL_RE.match(label):
            raise ValueError(f"Invalid domain label: {label!r}")

    return v
