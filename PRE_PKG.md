# PRE_PKG — Beta Pre-Flight Checklist

Target release window: **Tonight @ 00:00 local time**  
Release type: **Beta (v0.1.0-beta)**  
Primary artifact: **Single Docker image built from root `Dockerfile`**

---

## 1) Go / No-Go Rules

- [ ] **Critical blockers** resolved before release.
- [ ] **Mandatory Pi validation** completed (Raspberry Pi / ARM).
- [ ] Waivers (if any) documented with owner + rationale + expiry date.
- [ ] Rollback plan confirmed and tested (previous image/tag can be restored).

If a critical check fails and no approved waiver exists, **do not ship**.

---

## 2) Version & Release Integrity

- [ ] Confirm release version in:
  - [ ] `backend/pyproject.toml`
  - [ ] `frontend/package.json`
- [ ] Create/verify git tag format: `vX.Y.Z` or prerelease `vX.Y.Z-<label>` (example: `v0.1.0-beta`).
- [ ] Confirm release notes/changelog summary exists.
- [ ] Confirm repo remote points to canonical location (`BlkLeg/CircuitBreaker`).

Evidence:

- Tag/commit: ____________________
- Version sync checked by: ____________________

---

## 3) Platform Validation Matrix (Required for Beta)

### Linux Host

- [x] Docker image builds successfully.
- [x] Container starts and serves app on `http://localhost:8080`.
- [x] Health/API endpoint responds.
- [ ] Core UI smoke checks pass (login, topology map, CRUD basics).

### Windows

- [ ] Browser smoke run against containerized app.
- [ ] Key flows pass (login, map load, settings save).

### macOS

- [ ] Browser smoke run against containerized app.
- [ ] Key flows pass (login, map load, docs panel render).

### Raspberry Pi (CRUCIAL / Mandatory)

- [ ] Build or pull image on Pi/ARM host.
- [ ] App starts successfully on Pi.
- [ ] Core flows pass (login + topology render + one CRUD action).
- [ ] Performance sanity check acceptable for beta usage.

Evidence links/logs:

- Linux: Local smoke run (2026-02-28): container `circuit-breaker-beta-smoke` up on `:8080`, `GET /api/v1/health` => `{"status":"ok","version":"0.1.0"}`, `GET /api/v1/docs` => `200 OK`, root page GET succeeded, persistence marker `/data/.cb_persist_probe` survived restart using Docker volume `circuit-breaker-data`.
- Windows: ____________________
- macOS: ____________________
- Pi: ____________________

---

## 4) Docker Packaging Checks

- [x] `docker build -t circuit-breaker:beta .` succeeds.
- [x] `docker run --rm -p 8080:8080 -v circuit-breaker-data:/data circuit-breaker:beta` succeeds.
- [x] Static assets load in browser.
- [x] API reachable at `/api/v1/docs`.
- [x] Data persistence works across container restarts.

Optional hardening:

- [ ] Build + run with `docker/docker-compose.yml` smoke-tested.

---

## 5) Backend/API Quality Gates

- [x] Run backend tests (`pytest`).
- [x] Validate auth path behavior.
- [x] Validate graph topology endpoint and layout save/reload flow.
- [x] Validate cluster membership/link/unlink behavior from map.

Command log:

```bash
cd backend
source ../.venv/bin/activate
pytest -q
```

---

## 6) Frontend Quality Gates

- [x] Production build succeeds (`npm run build`).
- [x] No blocking console/runtime errors in critical pages.
- [ ] Map layout save/reload works across environments.
- [x] Screenshot/docs assets render correctly from README/docs.

Command log:

```bash
cd frontend
npm ci
npm run build
```

---

## 7) Security & Exposure Checks

- [ ] Beta security warning present in `README.md`.
- [ ] No direct public internet exposure for beta deployment.
- [ ] Secrets not committed (quick scan + config review).
- [ ] Dependency risk review completed (Snyk/Sonar/Dependabot context).

Waivers (if used):

- [ ] Check: ____________________
  - Risk: ____________________
  - Owner: ____________________
  - Expiry: ____________________
  - Mitigation: ____________________

---

## 8) GitHub Actions (Tonight Minimum)

- [ ] `dev-checks.yml` active for PR/push basic validation.
- [ ] `preflight.yml` runs backend tests + frontend build + Docker smoke.
- [ ] `release.yml` creates versioned release on `v*` tags.

Workflow run links:

- Dev checks: ____________________
- Preflight: ____________________
- Release: ____________________

---

## 9) Release Execution Timeline (Tonight)

- [ ] **T-4h**: Freeze features and run full preflight.
- [ ] **T-3h**: Complete Pi mandatory validation.
- [ ] **T-2h**: Resolve blockers, document waivers.
- [ ] **T-1h**: Tag release + verify Actions status.
- [ ] **T-0h (midnight)**: Publish beta + announce.

---

## 10) Final Signoff

- [ ] Packaging (Docker)
  - Owner: ____________________
  - Status: ☐ Pass / ☐ Blocked
  - Notes: ____________________
- [ ] Platform Matrix (Linux/Win/macOS/Pi)
  - Owner: ____________________
  - Status: ☐ Pass / ☐ Blocked
  - Notes: ____________________
- [ ] Backend/API
  - Owner: ____________________
  - Status: ☐ Pass / ☐ Blocked
  - Notes: ____________________
- [ ] Frontend/UI
  - Owner: ____________________
  - Status: ☐ Pass / ☐ Blocked
  - Notes: ____________________
- [ ] Security/Beta Risk
  - Owner: ____________________
  - Status: ☐ Pass / ☐ Blocked
  - Notes: ____________________
- [ ] Release Automation
  - Owner: ____________________
  - Status: ☐ Pass / ☐ Blocked
  - Notes: ____________________

Release decision: **☐ GO / ☐ NO-GO**  
Approved by: ____________________  
Timestamp: ____________________
