# Security Patch — Scanner False Positives & Runtime Artifact Suppression

**Scan date:** 2026-03-12  
**Patch scope:** Trivy / Gitleaks scanner findings — false positives and gitignored runtime artifacts

---

## Summary

Two categories of findings were investigated and suppressed with documented rationale:

| ID | Severity | Finding | Classification | Action |
|----|----------|---------|----------------|--------|
| FP-01 | MEDIUM | JWT token in `.venv/…/bearer.cpython-311.pyc` | False positive — third-party lib example | Scanner suppression |
| FP-02 | MEDIUM | JWT token in `apps/backend/.venv/…/bearer.cpython-314.pyc` | False positive — third-party lib example | Scanner suppression |
| RA-01 | HIGH | Private key in `docker/data/tls/privkey.pem` | Runtime artifact — gitignored, never committed | Scanner suppression |
| RA-02 | HIGH | Private key in `docker/circuitbreaker-data/tls/privkey.pem` | Runtime artifact — gitignored, never committed | Scanner suppression |

---

## Detailed Analysis

### FP-01 / FP-02 — JWT Token in fastapi_users Bytecode

**Root cause:** `fastapi_users/authentication/transport/bearer.py` (a third-party library) contains a hardcoded example JWT token in its OpenAPI schema documentation:

```python
"example": {
    "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1...",
    "token_type": "bearer",
}
```

This string is compiled into `bearer.cpython-*.pyc` bytecode, which Trivy's secret scanner detects as a JWT credential.

**Why this is a false positive:**
- The token is a static documentation example, not a live credential.
- The `.venv/` and `apps/backend/.venv/` directories are covered by `.gitignore` rules (lines 6 and 8), so these files are never committed to the repository.
- `git ls-files` and full git history confirm zero `.venv/` files are tracked.
- The token cannot be used to authenticate against any instance of this application because JWT secrets are generated dynamically at runtime (see patch C-04 in `security_patch.md`).

**Verification command:**
```bash
grep "access_token.*eyJ" .venv/lib/python3.11/site-packages/fastapi_users/authentication/transport/bearer.py
# → "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1"
# Confirmed: hardcoded documentation example only.
```

---

### RA-01 / RA-02 — TLS Private Keys in Docker Runtime Data Directories

**Root cause:** `docker/entrypoint-mono.sh` generates a self-signed EC certificate on first container start when no certificate is present:

```bash
# entrypoint-mono.sh lines 104-110
if [ ! -f "${DATA}/tls/fullchain.pem" ] || [ ! -f "${DATA}/tls/privkey.pem" ]; then
  mkdir -p "${DATA}/tls"
  openssl req -x509 -nodes -days 365 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \
    -keyout "${DATA}/tls/privkey.pem" -out "${DATA}/tls/fullchain.pem" \
    ...
fi
```

The keys land in `docker/data/tls/` and `docker/circuitbreaker-data/tls/` on the developer's host machine.

**Why these are not a security risk:**
- Both parent directories (`docker/data/` and `docker/circuitbreaker-data/`) are covered by `.gitignore` (lines 45 and 108), ensuring they are never committed.
- `git log --all -- '*.pem'` returns no results — no PEM file has ever appeared in git history.
- File permissions are already `600` (`rw-------`), restricting read access to the owning user.
- The private key has no passphrase (`-nodes`) as is standard for automated container startup; this is an acceptable trade-off for a self-signed dev/fallback cert.
- Production deployments should replace these with CA-signed certificates or use Caddy's automatic HTTPS (Let's Encrypt / ACME), which stores keys outside this path.

**Verification commands:**
```bash
git ls-files docker/data/ docker/circuitbreaker-data/   # returns nothing
git log --all --oneline -- '*.pem'                       # returns nothing
git check-ignore -v docker/data/tls/privkey.pem          # .gitignore:45:docker/data/
```

---

## Changes Made

### 1. `.trivyignore` (new file)

Created `.trivyignore` to suppress Trivy filesystem and config scans from scanning:
- `.venv/` and `apps/backend/.venv/` — third-party packages only
- `docker/data/tls/` and `docker/circuitbreaker-data/tls/` — runtime-generated certs
- `.claude/worktrees/` — agent checkout duplicates

### 2. `.gitleaks.toml` (updated)

Migrated from deprecated `[allowlist]` (v7) to `[[allowlists]]` (v8) format and added two new entries:
- `third-party-venv-example-tokens` — suppresses `.venv/` paths for the fastapi_users example JWT
- `runtime-tls-certs` — suppresses `docker/data/tls/` and `docker/circuitbreaker-data/tls/` for runtime certs

### 3. `scripts/security_scan.sh` (updated)

Both Trivy invocations (filesystem and config) now pass `--ignorefile /workspace/.trivyignore` so suppression rules are respected during CI/CD and manual scans.

### 4. `docker/.gitignore` (new file)

Added a directory-scoped `.gitignore` as belt-and-suspenders protection for `data/` and `circuitbreaker-data/` at the `docker/` level, in addition to the existing root `.gitignore` coverage.

---

## Residual Risk & Recommendations

| Item | Risk | Recommendation |
|------|------|----------------|
| Self-signed TLS cert (`-nodes`, 365 days) | Low (dev only) | Production: configure Caddy ACME / bring your own cert; rotate the dev cert by deleting `docker/data/tls/` and restarting. |
| fastapi_users pinned version | Low | Monitor upstream for any real vuln in `bearer.py`; update via `poetry update fastapi-users` when a fix is released. |
| Trivy version | Low | The `aquasec/trivy` image is pulled as `:latest` in the scan script; pin to a specific version tag for reproducible CI scans. |
