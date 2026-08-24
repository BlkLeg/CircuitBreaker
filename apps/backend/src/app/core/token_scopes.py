"""The scopes a token may be granted, and the presets the UI offers.

One source of truth, served to the frontend by GET /auth/scopes, so the picker
cannot offer something the validator rejects or the enforcement ignores.
"""

from __future__ import annotations

GRANTABLE_SCOPES: dict[str, str] = {
    "read:*": "Read every resource.",
    "write:*": "Create and modify every resource.",
    "delete:*": "Delete every resource.",
    "admin:*": "Administrative operations: settings, users, backups, vault.",
    "write:telemetry": "Submit telemetry samples. For collectors and agents.",
    "*:*": "Unrestricted. Equivalent to an administrator session.",
}

SCOPE_PRESETS: list[dict] = [
    {
        "key": "read_only",
        "label": "Read-only",
        "description": "Can read everything, change nothing.",
        "scopes": ["read:*"],
    },
    {
        "key": "telemetry_ingest",
        "label": "Telemetry ingest",
        "description": "Read access plus telemetry submission. For collectors.",
        "scopes": ["read:*", "write:telemetry"],
    },
    {
        "key": "read_write",
        "label": "Read and write",
        "description": "Can create and modify resources, but not administer the server.",
        "scopes": ["read:*", "write:*"],
    },
    {
        "key": "full_access",
        "label": "Full access",
        "description": "Unrestricted, including settings, users and the vault.",
        "scopes": ["*:*"],
    },
]


def validate_scopes(scopes: list[str]) -> list[str]:
    """Normalise and validate a requested scope list."""
    cleaned = [s.strip() for s in scopes if s and s.strip()]
    if not cleaned:
        raise ValueError("At least one scope is required.")
    unknown = sorted(set(cleaned) - set(GRANTABLE_SCOPES))
    if unknown:
        raise ValueError(
            f"Unknown scope(s): {', '.join(unknown)}. "
            f"Valid scopes: {', '.join(sorted(GRANTABLE_SCOPES))}."
        )
    return sorted(set(cleaned))
