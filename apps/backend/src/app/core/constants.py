"""Application-wide constants shared across modules."""

TELEMETRY_CACHE_TTL_SECONDS = 300

# Client wire hash (PBKDF2-HMAC-SHA256) — must match apps/frontend/src/utils/passwordHash.js
CLIENT_HASH_PBKDF2_ITERATIONS = 310_000
CLIENT_HASH_V2_PREFIX = "v2."
