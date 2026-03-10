"""Shared input validators for security-sensitive parameters."""

import re

# SNMP community string: allow only safe characters to prevent injection.
# Max length 64 per common SNMP limits.
_SNMP_COMMUNITY_RE = re.compile(r"^[a-zA-Z0-9_.\-]+$")
_SNMP_COMMUNITY_MAX_LEN = 64


def validate_snmp_community(community: str) -> str:
    """Validate SNMP community string. Returns the string if valid.

    Raises ValueError if community contains disallowed characters or exceeds length.
    Use before passing to subprocess or any SNMP client.
    """
    if not community or not isinstance(community, str):
        raise ValueError("SNMP community must be a non-empty string")
    c = community.strip()
    if len(c) > _SNMP_COMMUNITY_MAX_LEN:
        raise ValueError(f"SNMP community must be at most {_SNMP_COMMUNITY_MAX_LEN} characters")
    if not _SNMP_COMMUNITY_RE.match(c):
        raise ValueError(
            "SNMP community may only contain letters, numbers, underscore, period, and hyphen"
        )
    return c
