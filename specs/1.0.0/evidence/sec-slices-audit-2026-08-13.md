# SEC Slices Audit — First 10 Slices (v1.0.0 readiness)

**Date:** 2026-08-13
**Auditor:** independent read-only review (7 parallel domain agents + ledger meta-audit)
**Scope:** ledger rows SEC-01 … SEC-18 (slices SEC-1, SEC-2B, SEC-3, SEC-4, SEC-5, SEC-6), plus release-control process integrity
**Method:** verify each evidence claim against actual code and tests; no test suites re-run against the audited claims (source of truth is the working tree at branch `dev`, dirty).

## Bottom line

The **security engineering is largely real and often better than the evidence claims** (live-dependency-tree endpoint gate, real PostgreSQL `FOR UPDATE` first-admin race gate with a genuine 2-thread Postgres test, magic-byte upload validation with inert serving). But **not one SEC row currently meets the project's own definition of release evidence**, and the audit surfaced **8 substantive security gaps** that the "passed" statuses hide. The honest reading is: *implementation ~80% done, release evidence 0% done.*

Two independent auditors converged on the same real defect (mid-connection revocation missing on SSE/WebSocket), which raises confidence it is genuine.

---

## Verdict by requirement

| Req | Ledger says | Audit verdict | Note |
|---|---|---|---|
| SEC-01 | passed | VERIFIED (process gap) | ADR-0003 exists and records the deferral; but RC-03 ledger row never updated |
| SEC-02/03/04 | passed | VERIFIED-as-deferred | Vacuously true, but "passed" mislabels a waiver; RC-08 exception process doesn't exist yet |
| SEC-05 | in_progress | KNOWN-PENDING + gaps | Hard-disables real; topologies API still accepts client `tenant_id`; seed script behaviorful |
| SEC-06 | in_progress | KNOWN-PENDING | Gate is real (435 routes, 0 unclassified) but blind to sub-app mounts / auth-disabled semantics |
| SEC-07 | passed | GAP (evidence integrity) | Allowlist genuine; "passed" pinned to uncommitted files; **gate test fails on this machine** |
| SEC-08 | passed | GAP | 3 side channels leak monitor data without read scope; `/agents/{id}/probes` is HIGH |
| SEC-09 | passed | VERIFIED (local) | Real PG race gate; one unaddressed risk: pre-bootstrap anonymous-admin surface |
| SEC-10 | passed | PARTIAL | 7/8 claims verified adversarially; revocation only at connect/reconnect, not mid-connection |
| SEC-11 | in_progress | VERIFIED (local) | click 8.3.3 fixed; `requirements-pg.txt` unscanned |
| SEC-12 | in_progress | GAP | No DNS pinning anywhere; 11 outbound sites bypass the policy; monitors wholly outside it |
| SEC-13 | in_progress | GAP | Shared-Redis fail-closed is sound; **leftmost-XFF trust is spoofable behind shipped nginx** |
| SEC-14 | in_progress | VERIFIED (notes) | Fail-closed secret/dependency validation real; degrade flag is a plain env var |
| SEC-15 | passed | VERIFIED (caveats) | SVG/active content rejected + inert serving; one endpoint trusts client suffix |
| SEC-16 | passed | GAP (docs) | PG serialization sound; advisory lock fails **open**; repair not in operator docs |
| SEC-17 | passed | GAP | `DELETE /api/v1/logs` wipes the audit chain with no safeguard and no audit event |
| SEC-18 | passed | GAP + PENDING | Local gate ran; **no container image scan exists**; pip-audit absent from local gate |

---

## Remediation status (updated 2026-08-13, after commit `c68842b6`)

Verified on **Python 3.12.13 with FastAPI 0.135.1** in a container (the host has
only Python 3.14 and FastAPI 0.138.2, neither of which the project supports).

| Gap | Status | Change |
|---|---|---|
| P0-1 agent probes leak | **FIXED** | `api/agents.py` now uses `require_scope("read","*")` + per-row `reader_can_access_monitor`; regression test asserts a write-only token gets 403 |
| P0-2 audit-log wipe | **FIXED** | `api/logs.py` now requires `CLEAR_AUDIT_LOG` + idempotency key + verified backup, and writes `clear_audit_log_completed` as the surviving chain genesis; 3 new tests |
| P0-3 XFF spoofing | **FIXED** | `core/rate_limit.py` walks the chain right-to-left skipping trusted CIDRs; 4 new tests including identity-rotation |
| P0-5 monitor SSRF | **FIXED** | New `MONITOR_TARGET_POLICY` applied at request time in the web collector, with per-hop redirect re-validation; LAN/loopback still allowed, link-local/metadata refused; 3 new tests |
| P0-4 pre-bootstrap admin | **OPEN** | Needs a product decision (see below) |
| Gate blindness (audit finding #9) | **FIXED** | New `test_every_runtime_route_is_a_kind_this_gate_understands` fails on any unclassifiable route object |

### New findings discovered during remediation

1. **HIGH — dependency drift silently disables the SEC-06/07 gate.** `pyproject.toml`
   declared `fastapi>=0.111.0` unbounded while `requirements.txt` pins `0.135.1`,
   and CI installs from **pyproject** (`pip install -e "apps/backend/[dev]"`) — so CI
   resolves whatever is newest. From FastAPI **0.138** onward, `include_router`
   leaves an internal `_IncludedRouter` wrapper in `app.routes` instead of the
   flattened routes, and the inventory sees **4 routes instead of 428**. Bisected:
   0.136.0 good, 0.138.2 broken. The developer's own `.venv` is already on 0.138.2,
   so the SEC-07 "passes locally" evidence could not have been produced there.
   *Fixed:* bounded to `<0.137` with a comment, plus the new gate guard above.
2. **MEDIUM — four public endpoints were never covered by SEC-06 at all.**
   `/api/openapi.json`, `/api/docs`, `/api/redoc`, `/docs/oauth2-redirect` are plain
   Starlette `Route` objects, so every reconciliation test skipped them. They are
   unauthenticated and `/api/openapi.json` discloses the entire API schema.
   *Fixed:* declared in a new `framework_surfaces` policy section with disclosure
   rationale; the new guard test makes an undeclared one fail.
3. **LOW — no test covered `DELETE /api/v1/logs`.** That is how it shipped with no
   safeguard: nothing failed when the guardrail was absent.
4. **HIGH — the committed backend suite did not pass, and the failures were
   order-dependent.** *(RESOLVED — see "Suite restored to green" below.)* On the supported interpreter and pinned FastAPI, `pytest tests`
   at `c68842b6` exits 1 with **19 failures** (monitor scheduler/targets, monitor
   engine e2e, discovery auto-monitor, discovery probes, windscribe privacy score).
   Every one of them passes when its file is run alone or in small groups, so they
   are cross-test pollution, not broken logic. This matters for the ledger: several
   SEC rows cite whole-suite "pytest … pass locally" as their evidence method, and
   that run does not currently pass. Confirmed identical before and after this
   remediation (19 vs 19, same test ids), so it is pre-existing, not introduced here.
   Fixing it is REL-19/REL-20 work (test isolation), but it blocks any honest
   "suite green at the RC commit" claim.

### Suite restored to green (2026-08-13)

`pytest tests` now exits 0 with **zero failures** on Python 3.12.13 / FastAPI
0.135.1, down from 19. Three distinct root causes, none of them a product bug:

1. **Test-state leak (18 of 19 failures).** `tests/api/test_monitor_stream_auth.py`
   — added by the SEC-08 slice — commits a hardware row and a monitor per case
   through its own `SessionLocal`, because the stream handler opens its own
   session and cannot see the test's SAVEPOINT. That is the same constraint the
   agent suites hit, but `conftest.py`'s reaper only cleaned up `agents`, so the
   monitor rows survived into every later test and broke anything that counts
   monitors. Generalized the reaper to be table-driven (MonitorItem, Agent,
   Hardware, User, Tenant, deleted child-first).
2. **Time-bomb test.** `test_privacy_score_history_buckets_by_day_and_picks_latest`
   hardcoded 2026-07-13/14 while the endpoint only returns the last 30 days. It
   passed when written on 08-11 and began failing on 08-12 for a reason unrelated
   to what it tests. Dates are now relative to today.
3. **A test that never actually ran.** `test_arp_scan_accepts_16_subnet` read the
   module global `_ARP_CAPABLE`, which is `None` until `_arp_available()` fills it
   in — so the guard skipped the test rather than running it. Once anything
   earlier in the session probed the capability, the skip stopped firing and the
   test failed, because its patch target was wrong too: `srp` is imported inside
   the function, so it must be patched in `scapy.sendrecv`. Now it calls the
   capability function, patches the right target, and asserts `srp` was invoked.

Also fixed while making the project's own gates green: 2 mypy errors in
`ws_monitors.py` and `auth.py` (both real `Optional` narrowing gaps in SEC-08/SEC-10
code, fixed rather than suppressed) and 6 ruff findings in untouched test files.
`ruff check src/app` and `mypy src/app` (the `make lint` gates) both pass clean.

Worth noting for REL-19/REL-20: two of these three were tests that reported
success without exercising their subject. A green suite is not the same as a
covering one.

### Verification performed for this remediation

Baseline and post-change full-suite runs were compared on the same environment:
both produce **exactly the same 19 pre-existing failures** — zero regressions. Every
file touched here (endpoint policy gate, destructive actions, rate limit, monitor
collector, SEC-10 controls, agents API, monitor API, monitor stream auth) passes:
200+ tests, exit 0. `ruff check` and `ruff format --check` are clean on all changed
files. The endpoint inventory was regenerated and its only delta is the intended
`require_role` → `require_scope` change on `get_agent_probes`.

### Still open — needs your decision

**P0-4, pre-bootstrap anonymous-admin.** `core/security.py:343-344` returns the
user-id-0 admin sentinel for every anonymous request while `auth_enabled` is false.
Closing it means restricting the pre-bootstrap surface to an allowlist
(bootstrap/onboarding/status), which changes OOBE behavior and risks breaking the
first-run wizard. The alternative is documenting private-network binding as the
accepted control and recording it as an RC-08 exception. I did not pick for you.

## Prioritized gaps to fill

### P0 — block RC (security holes contradicting a "passed" claim)

1. **Monitor data readable without read scope or tenant filter via agent probes.**
   `apps/backend/src/app/api/agents.py:455-502` — `GET /agents/{id}/probes` returns full monitor rows (id, name, host, check_type, status) behind only `require_role("viewer")`, which ignores token scopes and treats service uid 0 as admin. A **write-only/empty-scope token reads all monitors**, cross-tenant enumerable. Fix: `require_scope("read","*")` + `filter_readable_monitors`.

2. **Audit-log wipe destroys its own evidence with no safeguard.**
   `apps/backend/src/app/api/logs.py:295-302` — `DELETE /api/v1/logs` deletes every `Log` row (hash chain included) on a bare admin check: no typed confirmation, no backup header, **no audit event of the wipe**. Highest-impact destructive action, least protected; makes SEC-16 tamper-evidence moot. Fix: route through `require_destructive_confirmation`, export before delete, write a `logs_cleared` genesis event.

3. **Rate-limit identity spoofable behind the shipped reverse proxy.**
   `apps/backend/src/app/core/rate_limit.py:110-127` trusts the **leftmost** `X-Forwarded-For`, but `deploy/nginx/circuitbreaker-tls.conf:56` *appends* (`$proxy_add_x_forwarded_for`). An external client sets its own XFF and rotates identities to bypass login/MFA limits. Fix: walk XFF right-to-left skipping trusted CIDRs, or have nginx overwrite with `$remote_addr`.

4. **Pre-bootstrap API is anonymous-admin.**
   `apps/backend/src/app/core/security.py:343-344` — when `auth_enabled` is false (setup window) every anonymous request is user-id-0 admin. Setup token gates only first-admin creation, not settings/OAuth-provider mutation, so a network attacker in the window can poison the operator's OAuth bootstrap. Same sentinel returns under `CB_LEGACY_AUTH` rollback for all 400+ "authenticated" routes. Fix: allowlist bootstrap/onboarding/status endpoints pre-bootstrap, or document+enforce private-binding as the accepted control.

5. **No DNS pinning — rebinding TOCTOU intact; policy not universally applied.**
   `apps/backend/src/app/core/url_validation.py:198-205` validates by resolution then re-issues by hostname (httpx re-resolves). 11 outbound call sites bypass the shared policy/proxy entirely; **monitor HTTP checks** (`services/monitoring/collectors/web.py:34`, `integrations/native_probe.py:108`) apply zero validation and can hit loopback/link-local/metadata with arbitrary methods, headers, bodies, and unvalidated redirects. Fix: pin to the validated IP (Host/SNI override) and route all clients through it; apply at least the LAN policy to monitor URLs at create + request time.

### P1 — fix before tag

6. **Mid-connection revocation missing on SSE/WebSocket** (found independently by two auditors). `api/ws_monitors.py:353-401` and `api/events.py:168-169` authenticate only at handshake; a revoked/expired session keeps receiving monitor + alert data until it disconnects. Fix: revalidate in the ping/poll loop or push a revocation close.
7. **No container image vulnerability scan** despite SEC-18 naming "container … scans". `scripts/security_scan.sh` only does `trivy fs`/`config`; `release.yml` builds/signs/SBOMs but never `trivy image`. Add an image scan against the pushed digest.
8. **Graph topology + integration monitor listings leak monitor rollups** without the read-scope/tenant filter (`api/graph.py:387-405`, `api/integrations.py:158,240,295`). Fix: run through `filter_readable_monitors` / add `require_scope("read","*")`.
9. **8 mutating "auth-internal" routes bypass the endpoint gate** (account delete, MFA disable at `endpoint_policy.json:93-164`) — checks live in-handler where the dependency-tree gate is blind. Migrate to dependencies.
10. **Topologies API still accepts and filters by client-supplied `tenant_id`** (`api/topologies.py:99-143`, schema `:36`) — a live tenant-selection surface contradicting SEC-2B. Drop the field or ignore it.
11. **Icon upload trusts client filename suffix** (`api/compute_units.py:165`) — PNG-magic body named `x.html`/`x.pdf` stored/served under that suffix; single layer of defense (serving middleware), `.pdf` not in the override list. Derive suffix from validated content type.
12. **`.gitleaks.toml` allowlists bypass suppression governance** — 6 allowlist blocks (incl. live-looking `.env` paths) with no owner/reason/expiry in `security-suppressions.json`; validator only checks `.trivyignore`/`.gitleaksignore`. Extend the validator.
13. **Security gate silently passes when Gitleaks/Trivy binaries are absent** (`security_scan.sh:130-132,209-211`) — RC rerun could regress undetected. Fail closed on missing scanners.

### P2 — pre-GA cleanup
- Challenge tokens (force-change / MFA) don't re-check lockout at redemption (`api/auth.py:376-379,1072-1074`).
- Session-validation cache serves revoked tokens up to 10 s, per-process only (`core/security.py:33`).
- OAuth base URL / cookie `Secure` / HSTS trust `X-Forwarded-Host`/`-Proto` from any peer (inconsistent with the XFF trusted-proxy model).
- LAN integrations (Proxmox, iLO, OPNsense) validate at persist time only, not at connect (rebinding).
- OIDC discovery/token/JWKS use a weaker parallel validator and bypass the egress proxy.
- `requirements-pg.txt` (asyncpg, psycopg2) scanned by no pip-audit job.
- Audit advisory lock fails open and the concurrency test can't detect its loss (single-process threads).
- Tenant seed script (`scripts/seed_default_team.py`) + monitor legacy-tenant read rule remain behaviorful; UI still surfaces "different tenant" strings.
- Health endpoint leaks version/extension detail anonymously (`main.py:1948-1957`).
- MFA verification failures never feed the lockout counter (rate-limit only).

---

## Release-control / process integrity (independent of code)

These make the ledger untrustworthy as evidence *even where the code is correct*:

- **CRITICAL — SEC-09 evidence digest is stale but still `current`.** Recorded `sha256:a36782…`; actual file hash `sha256:152378…` (the SEC-10 commit rewrote the file). Their own invalidation rules require `superseded`/`invalidated`; neither happened.
- **CRITICAL — "passed" flips live only in an uncommitted dirty tree** that also modifies the security code under test (`ws_monitors.py`, `endpoint_policy.json`, `endpoint_inventory.json`, tenant/monitor/policy tests). Committed HEAD still says SEC-01 `in_progress`, SEC-02/03/04 `not_started`. All passed rows pin `working-tree@<sha>` — a non-reproducible state the definition of done forbids ("A test passing in a development tree is supporting evidence, not release evidence").
- **HIGH — SEC-15…18 evidence never invalidated** despite later `impact:runtime-code` commits touching `upload_validation.py`, `audit_chain.py`, `destructive_actions.py`, `core/security.py`, `core/rbac.py`. Worse, SEC-15/16/17 completion time (14:05Z) *predates* the commit (`bec22281`, 14:21Z) that introduced the tested code — the pinned tree doesn't contain what the evidence covers.
- **HIGH — SEC-02/03/04 recorded `passed` for deferred requirements** while RC-08 (the exception process) is `not_started` and `exception-register.csv` is empty; RISK-001 (P0) is still open for exactly these rows. Circular.
- **MEDIUM — completion timestamps look reconstructed** (six rows share `2026-08-11T20:26:52Z` to the second, 3h47m after the pinned commit; SEC-15…18 share a round `14:05:00Z`).
- **MEDIUM — the project's own validator gives false assurance.** `scripts/validate_v1_release_control.py` exits 0 despite the stale digest and `working-tree@` pins — it validates schema shape only, never recomputes `sha256sum`, never rejects `working-tree@`, never cross-checks "rerun pending" notes against `status=passed`.
- **MEDIUM — no named owners** (RC-07 `not_started`; `owner-map.md` is "draft pending named-person assignment"); every row is `security-owner`/`release-owner` placeholders, so no distinct reviewer sign-off exists.

## Environment / reproducibility

- **The local machine has only Python 3.14.6; the project and CI require 3.12** (`pyproject.toml` `requires-python >=3.12,<4`, `ci.yml` pins 3.12). There is **no `python3.12` on this host**, so the "passes locally" evidence cannot be reproduced here at all.
- Running the backend suite under 3.14 produced **20 failures**, including the **SEC-07 gate itself** (`test_endpoint_policy_inventory.py` — 38 auth/bootstrap/oauth/agent routes present in the policy but absent from the runtime app the test builds). This clusters with the monitor scheduler/target failures and is consistent with an interpreter-version artifact, **not confirmed as a regression** — but it means local gate results on this machine are not authoritative and must be run on 3.12.

---

## Recommended sequence to "fill gaps and continue"

1. **Commit the dirty tree** (11 files) so the SEC-05/06/07/08 evidence pins an immutable SHA; re-run gates at that SHA on **Python 3.12**.
2. **Fix P0 #1–#5** (all are security holes under a currently-"passed" or nearly-passed claim). These are small, localized diffs.
3. **Harden the release-control validator** to recompute digests, reject `working-tree@` pins, and fail `passed` rows whose notes contain "pending"; then re-truth the ledger (invalidate SEC-09 and SEC-15…18, demote over-claimed rows).
4. **Stand up RC-08 + RC-07** (exception register + named owners) and move SEC-02/03/04 to `excepted`, since the whole SEC workstream leans on a deferral mechanism that formally doesn't exist yet.
5. Work P1, then P2.

Full per-slice evidence (surface tables, claim tables, file:line citations) is in the seven agent reports summarized above.
