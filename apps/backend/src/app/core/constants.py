"""Application-wide constants shared across modules."""

TELEMETRY_CACHE_TTL_SECONDS = 300

# Client wire hash (PBKDF2-HMAC-SHA256) — must match apps/frontend/src/utils/passwordHash.js
CLIENT_HASH_PBKDF2_ITERATIONS = 310_000
CLIENT_HASH_V2_PREFIX = "v2."

# ── Privacy scoring (specs/2026-07-15-windscribe-privacy-completion-design.md) ─
PRIVACY_MAX_SCORE = 100
PRIVACY_MIN_SCORE = 0
# Network score: sum the N largest device deductions, capped at this many points
PRIVACY_DEVICE_AGGREGATE_TOP_N = 10
PRIVACY_DEVICE_AGGREGATE_CAP = 40
# Any critical network check clamps the network score to at most this (F band)
PRIVACY_CRITICAL_CHECK_CEILING = 55
# Gateway-role devices escalate deduction points by this multiplier (ceil)
PRIVACY_GATEWAY_POINTS_MULTIPLIER = 1.5
# Grade thresholds, highest first: score ≥ threshold ⇒ grade
PRIVACY_GRADE_BANDS = (("A", 90), ("B", 80), ("C", 70), ("D", 60))
PRIVACY_FALLBACK_GRADE = "F"

# ── Threat feed (public blocklists) ───────────────────────────────────────────
FEED_CACHE_KEY = "privacy:threat_feed"
FEED_FETCH_TIMEOUT_S = 15.0
FEED_MAX_RESPONSE_BYTES = 5_000_000
FEED_SOURCE_PUBLIC_BLOCKLISTS = "public_blocklists"

# ── Hostile-network checks ────────────────────────────────────────────────────
CAPTIVE_PORTAL_CHECK_URL = "http://clients3.google.com/generate_204"
CAPTIVE_PORTAL_EXPECTED_STATUS = 204
NETWORK_CHECK_TIMEOUT_S = 5.0
# Canary domains with globally-stable answers, used to detect DNS tampering
DNS_CANARIES: dict[str, frozenset[str]] = {
    "one.one.one.one": frozenset({"1.1.1.1", "1.0.0.1"}),
    "dns.google": frozenset({"8.8.8.8", "8.8.4.4"}),
}
# How many feed malware domains to sample for the dns_filtering_absent check
DNS_FILTERING_SAMPLE_SIZE = 3
