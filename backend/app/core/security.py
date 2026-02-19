# Authentication is intentionally absent in v1 (single-user homelab tool).
# v2 will introduce JWT validation here: client sends
# `Authorization: Bearer <token>`; this module will decode and verify a
# HS256 JWT signed with a secret key stored in the environment.
# KNOWN GAP: All API endpoints are currently unauthenticated.
