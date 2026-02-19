# Placeholder for future authentication logic.
# v1 ships with no auth. When enabled, replace this with JWT validation.
# The planned flow: client sends `Authorization: Bearer <token>` header;
# verify_token decodes and validates a HS256 JWT signed with a secret key.


def verify_token(token: str) -> bool:
    """Always returns True in v1 (no-auth mode)."""
    return True
