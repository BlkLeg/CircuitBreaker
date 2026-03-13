# SECURITY_PATCH-3 Finding Matrix (C/H/M)

Date: 2026-03-12
Source: `SECURITY_PATCH-3.md`

## Classification Legend

- `current-code`: issue is present in current HEAD and requires code/config remediation.
- `history-only`: issue is not present in current HEAD but appears in repository history.
- `false-positive`: scanner report does not match actual code exposure.

## Critical Findings

| ID | Finding | Status | Evidence | Required Action |
| --- | --- | --- | --- | --- |
| C1a | GitHub PAT in `.github/workflows/.env` | false-positive | File is not present in HEAD and has no git history entries. | Keep `.github/workflows/.env*` ignored and enforce secret scanning. |
| C1b | API key in `KNOWN_BUGS.md` | current-code (documentation pattern only) | File contains placeholder examples like `your-password` and `re_your_api_key`. | Replace risky-looking placeholders with explicit non-secret placeholders. |
| C1c | Hardcoded API key in `0020_merge_heads.py` | false-positive | File contains only merge-head metadata and empty `upgrade()/downgrade()`. | No code fix needed beyond recurring scan gate. |
| C1d | JWT secret in `docker/circuitbreaker-data/backend_api_err.log` | history-only | Path is not tracked in HEAD; `git log --all -- docker/circuitbreaker-data/backend_api_err.log` shows prior tracked history. | Treat as leaked artifact: rotate runtime secrets, keep path ignored, add redaction controls. |
| C1e | TLS private key in `docker/circuitbreaker-data/tls/privkey.pem` | false-positive (HEAD), potential runtime artifact risk | Not tracked in HEAD and no git history entry for that file path in this clone. | Keep runtime key material out of git, preserve ignore rules, rotate certs if shared. |

## High Findings

| ID | Finding | Status | Evidence | Required Action |
| --- | --- | --- | --- | --- |
| H1 | Root runtime execution in images | current-code | `Dockerfile`, `docker/backend.Dockerfile`, `Dockerfile.mono` run as root at container runtime. | Move to non-root runtime user model and verify in CI. |
| H2 | MD5 usage | current-code (approved scope + guardrail gap) | MD5 is used only for Gravatar in backend/frontend helper, but no policy enforcement test existed. | Keep Gravatar-only usage, add policy annotations and regression guard tests. |

## Medium Findings

| ID | Finding | Status | Evidence | Required Action |
| --- | --- | --- | --- | --- |
| M1 | Sensitive data in logs | current-code | Existing scrubbers are partial and do not centrally sanitize all logger output. | Add global logging redaction filter and regression tests. |
| M2 | Nginx header/proxy hardening gaps | current-code | `X-Frame-Options` was `SAMEORIGIN`; proxy upgrade headers not explicitly cleared on non-WS locations. | Harden headers and clear `Upgrade`/`Connection` where WS is not expected. |
| M3 | Unsafe `/tmp` usage | current-code | Worker heartbeat files and cert renewal temp paths used hardcoded `/tmp`. | Move to controlled `/data` temp/heartbeat locations. |
| M4 | WSS enforcement regression risk | current-code (tests missing) | Hook logic already derives `wss` on HTTPS, but no regression tests existed. | Add explicit tests covering HTTPS->WSS and HTTP->WS behavior. |
| M5 | Default host bind on all interfaces | current-code | `apps/backend/src/app/start.py` default host was `0.0.0.0`. | Change default to `127.0.0.1` with env override for container use. |

## Immediate Containment Checklist

- Rotate live secrets used in active environments (`CB_DB_PASSWORD`, `CB_VAULT_KEY`, `NATS_AUTH_TOKEN`, JWT secret) after any confirmed artifact exposure.
- Remove/quarantine local runtime artifacts under `docker/circuitbreaker-data/` from all shared distribution channels.
- Keep `.gitignore` protections for runtime data and workflow `.env` files.
- Enable pre-commit and CI-level secret scanning to block recurrence.
