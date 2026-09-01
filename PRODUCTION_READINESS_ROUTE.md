# Circuit Breaker — Production-Readiness Route

**Date:** 2026-08-30 · **Baseline:** `ARCHITECTURE_ASSESSMENT.md` (branch `dev` @ `52364918`) · **Revalidated at:** HEAD `240bc3c6`
**Method:** every route-controlling finding re-checked against the current checkout (code authoritative over the report); two additional evidence passes (finding revalidation; navigation-responsiveness trace). No production code changed in this planning pass.

**Goal acknowledged:** turn a working, actively-used self-hosted product into one users can trust with their home infrastructure — enterprise engineering quality with self-hosted operational simplicity. The route below is the smallest sequence of high-confidence changes that materially improves production trustworthiness, keeping the modular monolith + independent Go agent unless a measured trigger fires.

---

## 1. Production standard and scope

"Production-ready" for Circuit Breaker, in observable terms: **on a supported install, every advertised feature runs; no stated product promise (air-gap, credential custody, revocability, backward-compatible upgrade) can be silently violated; failures are visible to the operator; and a release can be installed, upgraded, and rolled back by one person following documented steps.**

This route deliberately builds on the verification program the repo already has — ADR 0005's tiers (T0 static → T1 unit/integration → T2 composed → T3 artifact-on-VM) and the `specs/1.0.0` requirement ledger. New gates slot into those tiers; nothing below invents a parallel process. (Verified: `docs/adr/0005-verification-tiers-and-platform-support.md`; `specs/1.0.0/release-control/requirement-ledger.csv`.)

### Release blockers (must be true before the next production-quality release)

| # | Condition | Why it blocks | Finding |
|---|---|---|---|
| B1 | Monitor engine runs on every supported install topology, proven by a Tier 3 assertion (not just boot/readyz) | A supported package that silently never monitors violates the product contract | F5 |
| B2 | `CB_AIRGAP=true` provably blocks all application-initiated outbound HTTP, enforced at one choke point with a build-policy test | Stated promise, currently violated by CVE sync | F1 |
| B3 | Backup artifacts that leave the host (S3) are encrypted; the vault key never leaves in plaintext | Credential custody promise | F2 |
| B4 | Every session token is minted by one issuer and is revocable (session row always recorded) | The B28 defect class is a silent trust violation | F11 |
| B5 | ~~Tier 1 platform support (deb/rpm amd64 install/boot/upgrade/rollback) moves to "in force" in the ADR 0005 table~~ **Corrected 2026-08-30: not achievable at 0.4.0.** ADR 0005's Tier 1 criterion is "the `mode: upgrade` row passes against a release candidate", and no released version boots from its own deb/rpm, so 0.4.0 has no installable N-1 to upgrade *from*. Restated: **0.4.0 ships as the N-1 fixture** — deb/rpm `mode: install` rows green on CI artifacts, the artifacts and their digests published and retained, and the ADR table's Tier 1 row annotated with the fixture and the version its evidence will arrive at (`0.4.0 → 0.5.0`). Tier 1 goes in force at 0.5.0. (Verified, `docs/design/2026-08-28-verification-phase3-plan.md`: "the earliest honest evidence is `0.4.0 → 0.5.0`") | Upgrade path is part of the contract | F5-adjacent |
| B6 | The documented latent pytest e2e-mark collection failure is fixed — "a gate may not pass by not running" is ADR 0005's own rule | Gate integrity | F19 (partial) |

### Reliability objectives (measured targets; set numbers only where defensible)

| Objective | Target | Status of the number |
|---|---|---|
| Monitor scheduling lag | < shortest supported poll interval, sustained at Tier C workload (§5) | Defensible now (assessment) |
| Topology load p95 | < ~2 s at 500 entities | Defensible now (assessment) |
| Navigation wedge rate | Provisional ambition: 0 wedges / 500 navigations under the contention scenario | **Measured 2026-09-01: 12 / 30 (40%) at 6× CPU throttle**, all leaving `/map`, all on the H1 branch. `make nav-wedge` reproduces it; the number is the before-baseline R1 has to move |
| Event-loop lag p99 | To be set after the loop-lag gauge exists; collect 4 weeks at Tier B/C before fixing | Needs measurement |
| Backup restore | Every release rehearses a full restore from an encrypted snapshot in Tier 3 | Procedural, no number needed |
| Background-job failure visibility | 0 silent poison-message loops: every JetStream max-deliver exhaustion produces an operator-visible record | Procedural | 

### Deferred (valuable, not prerequisites)

`db/models.py` domain split (F8), frontend page splitting (F22), `response_model` coverage (F23), CSP nonces (F15), repo hygiene (F21), asyncpg migration (explicitly not planned — see constraints), staged fleet agent updates, per-agent admin partitioning.

---

## 2. Revalidated baseline

`git diff 52364918..HEAD --stat` shows only six files changed (packaging scripts + build tests + docs); no backend, frontend, or agent source moved. Consequently **no assessment finding is Fixed**; F5's neighborhood improved (boot/upgrade/rollback repaired) but its core defect stands. All statuses below re-verified at `240bc3c6`.

| Finding | Status at HEAD | Evidence | Changes the route? |
|---|---|---|---|
| F1 air-gap not central; CVE sync unguarded | **Fixed in working tree; release evidence pending** | `core/egress.py` owns HTTP construction and env/DB air-gap state; T0 AST ratchet plus public-before-DNS/private-mixed-DNS tests | Phase 1 (B2) |
| F2 plaintext vault key in S3-bound backup | **Fixed in working tree; release evidence pending** | S3 receives only temporary `.tar.gz.age` derivatives; recipient migration/API/UI and identity-based restore implemented | Phase 1 (B3) |
| F3 unsigned agent binaries | **Still verified** | `apps/agent/internal/update/update.go:144` SHA-256 only; the new `packaging/circuit-breaker-release-key.asc` is the package-repo key, not wired to agent self-update | Phase 4; DoD gate for agent expansion |
| F4 TLS pin rotation unsolved | **Still verified** | `internal/config/config.go:16` single `TLSPin`; `link.go:900-935` rotates only the Noise server key; no pin frame in `frame.go` | Phase 4; DoD gate for agent expansion |
| F5 packaged install runs no monitor workers | **Fixed in working tree; Tier 3 artifact evidence pending** | Packages ship coupled worker units and `cb`; Tier 3 creates a scheduled TCP monitor and requires an `avail` sample at every lifecycle state | Phase 1 (B1) |
| F6 route-layer DB access | Still verified | 354 grep matches in `api/` (pattern differs from original 246; same ballpark-or-worse) | Phase 3 ratchet |
| F7 core→services inversion | Still verified | `core/destructive_actions.py:10` (top-level), `core/scheduler.py:86-115`, `core/security.py:259,487,513` | Phase 3 ratchet |
| F8 models.py monolith | Still verified | 2,846 lines / 85 classes, unchanged | Deferred |
| F9 main.py lifespan | Still verified | 2,519 lines; lifespan 549→yield 1558 | Phase 3 |
| F10 WS auth duplication | Still verified | `api/ws_monitors.py:225,253` raw `jwt.decode` | Phase 3 |
| F11 multiple token-minting paths | **Fixed in working tree; release evidence pending** | Full sessions, including demo/MFA/OAuth/recovery/masquerade, use `issue_session`; JWT login router removed; T0 issuer ratchet active | Phase 1 (B4) |
| F12 sync sessions in async handlers | Still verified | 48 `async def` endpoints with sync `Session`; `get_async_db` usages in api/ = 0; `db/session.py:30-47` unchanged | Phase 2 (nav-critical subset first) |
| F13 silent exception swallows | Still verified | 107 `except:`+`pass`, identical count | Phase 3 ratchet |
| F14 no dead-letter on JetStream consumers | Still verified | no max_deliver/park in `telemetry_ingest_worker.py`, `monitor_poll_worker.py` | Phase 3 |
| F15 CSP `unsafe-inline` | Still verified | `nginx.mono.conf:182` | Deferred/Phase 4 |
| F16 Redis fail-closed agent plane | Still verified | `agent_enrollment.py` untouched | Documented risk; no change |
| F17 agent_events outside hash chain | Still verified | zero `audit_chain` refs in `agent_registry.py` | Phase 4 (agent-expansion gate) |
| F18 no load test / baseline | Still verified | nothing under tests/ or e2e; **note:** `make verify-fleet` is install-verification, not load | Phase 2 |
| F19 pre-push skips backend suite; latent collection failure | **B6 closed** | Root `pytest.ini` registers `e2e`; 13 agent E2E tests collected on 2026-08-30 | Phase 1 (B6) |
| F21 hygiene drift | Still verified | legacy `Dockerfile`, `deploy/`, root exhaust all present | Deferred |
| F24 unthrottled protocol_violation writes | Still verified | `services/agent_link.py:428-437` commits per malformed frame | Phase 3 (small) |
| F25 topology mode implicit in mono | **Fixed in working tree** | API and every dedicated worker receive explicit `CB_TOPOLOGY_MODE`; worker startup logs resolved ownership | Phase 1 |

New facts that shape the route (all Verified):
- **ADR 0005 + `specs/1.0.0` ledger is real gate infrastructure** (tiers, evidence hashes, exception registers). New gates below name their tier.
- **Phase 3's own register found that no released deb/rpm ever booted** — upgrade tests currently run against synthetic fixtures. The next release is therefore also the first real N-1.
- **The navigation bug is already partially characterized** in `known_bugs-v1.0.0-rc.1.md` item 1: 3 wedges/~180 navigations under CPU contention; URL advances, old route stays mounted at opacity 1; `AnimatePresence mode` statistically ruled out (2/48 vs 1/48).

---

## 3. Priority route

Four phases, ordered by risk reduction and dependency. Scoring model per work item: **T** = user trust/blast radius, **L** = likelihood/current user impact, **C** = production confidence gained, **E** = effort (5 = hardest), **D** = dependency urgency (all 1–5). No composite score — order is judgment, stated.

### Phase 1 — Supported installs are correct; silent promise violations closed

#### Implementation progress (updated 2026-08-30)

- [x] Worker ownership/package implementation: explicit API/worker topology, dedicated integration worker, least-privilege systemd units, mono inventory, packaged `cb`, and restore/status/log inventories.
- [x] Tier 3 scheduled-monitor assertion implemented for fresh, previous, upgraded, and rolled-back states; deb/rpm artifact execution evidence is still required before B1/SRV-02 closes.
- [x] Central air-gap decision point implemented in `app.core.egress`; public HTTP is rejected before DNS and private-LAN resolved sets reject unresolved/mixed/public answers. All server-side HTTP construction is migrated and the T0 AST ratchet is active.
- [x] S3 upload implementation encrypts a temporary `.tar.gz.age` derivative and fails closed without a valid operator-held X25519 recipient; local v1 tarballs remain unchanged. Settings/migration/UI and both restore CLIs accept the new format.
- [x] Full-session issuance centralized through `issue_session`, including one-hour demo and 15-minute masquerade row expiry; the parallel `/api/v1/auth/jwt/login` route is removed, user-management routes remain, and the T0 issuer ratchet is active.
- [x] B6 gate integrity revalidated: root `pytest.ini` registers `e2e`; `pytest apps/agent/e2e --collect-only -q` collected 13 tests on 2026-08-30.
- [x] B3 made exercisable and asserted end-to-end. The encryption was implemented but had no caller outside a configured S3 bucket and no unstubbed test — every `age_encryption` test replaced `subprocess.run`, so `age` had never actually run, and no tier could take the round trip. Closed by `cb backup --encrypt-to` / `cb snapshot encrypt` / the packaged binary's `--snapshot-encrypt` (one encryptor, three entry points, no second implementation), `t3::exercise_encrypted_snapshot_roundtrip` in `scripts/ci/tier3-artifact.sh`, and `tests/build/test_encrypted_backup_contract.py`. The tier asserts both halves against the bytes — the vault key is present in the local tarball and absent from the derivative, the derivative is not readable as a tar, a known record survives the restore, a row written after the snapshot does not, and an unrelated identity is refused.
- [x] All Phase 1 source implementation and T0/T1 contract work complete. `make verify` green at this commit.
- [ ] **B1–B4 pending release evidence only.** No source work remains; what is missing is a Tier 3 run against CI-built artifacts. `tier3-artifact.sh` refuses to evidence a locally built candidate on purpose (`built_by=local` ⇒ development run, ADR 0005 Phase 3 F8), and the last four fleet rows were run against local builds *and* predate both the scheduled-monitor and encrypted-backup assertions. See §8.
- [ ] **B5 cannot close at 0.4.0, and the blocker as written is unachievable.** ADR 0005's Tier 1 row is a single claim — install, boot, upgrade **and** roll back — whose criterion is "the `mode: upgrade` row passes against a release candidate". No released version boots from its own deb/rpm (Verified, `docs/design/2026-08-28-verification-phase3-plan.md`), so the only N-1 available to 0.4.0 is one that cannot be installed and booted, and the upgrade half has nothing honest to run against. That document reaches the same conclusion independently: "the earliest honest evidence is `0.4.0 → 0.5.0`". 0.4.0 is therefore the **fixture release** — it makes Tier 1 evidenceable rather than in force. See §8 for what this changes in the DoD.

**Objective:** every supported topology runs the whole product; no stated promise can be silently broken. **Risk addressed:** users trusting a package that doesn't monitor, an air-gap that leaks, a backup that hands out the vault key, a session that can't be revoked.
**Findings:** F5, F25, F1, F2, F11, F19(B6). **Complexity: M overall.**

| Slice (independently reviewable PR) | T | L | C | E | D | Why this order |
|---|---|---|---|---|---|---|
| 1.1 Package worker units: ship `circuit-breaker-worker@.service` (or equivalent) in nfpm contents for monitor_scheduler / monitor_poll / monitor_probe_dispatch + the four in-process-capable workers where topology demands; postinstall enables them; `cb` CLI knows them | 5 | 5 | 5 | 3 | 5 | B1. Everything else in the packaged story is moot while the engine doesn't run |
| 1.2 Tier 3 monitoring assertion: extend `tier3-artifact.sh` exercise step — create one ICMP/TCP monitor via API, assert a sample lands within 2× interval; flips ledger SRV-02 | 5 | 5 | 5 | 2 | 5 | The contract test that keeps 1.1 true forever; same-PR-train as 1.1 |
| 1.3 Set `CB_TOPOLOGY_MODE` explicitly in `Dockerfile.mono`/compose and log resolved ownership at worker start (F25) | 2 | 2 | 3 | 1 | 3 | One line + log; removes the ambiguity 1.1 would otherwise inherit |
| 1.4 Central egress gate: one `core/egress.py` helper wrapping outbound HTTP; airgap + `CB_EGRESS_PROXY_URL` checked there; migrate `cve_service`, `threat_feed`, update check, webhooks, SMTP/ACME (documented operator-egress exemptions allowed but *named* in code); build-policy test (T0) forbidding `httpx.`/`requests.` imports outside the helper + frozen allowlist | 5 | 4 | 5 | 3 | 4 | B2. The test is the point; the migration is mechanical |
| 1.5 Encrypt S3-bound backups (age or GPG passphrase, key material **not** stored in the app runtime env — passphrase supplied via config the operator holds); restore path + `cb restore` handles both formats; Tier 3 restore rehearsal asserts decrypt-and-restore | 5 | 3 | 4 | 3 | 3 | B3. Do after 1.4 so the S3 upload also rides the egress gate |
| 1.6 Single token issuer: `issue_session()` used by login, invite, demo, OAuth; wrap or remove the parallel FastAPI-Users JWT route (`main.py:1828,1836`); regression test: every 200 from any auth surface yields a token revocable via session revocation | 5 | 3 | 4 | 2 | 3 | B4. Small, sharp, closes a recurring defect class |
| 1.7 Fix the latent pytest collection failure (B6) | 3 | 3 | 3 | 1 | 2 | Gate integrity; trivial |

**Acceptance:** Tier 3 matrix green including the new monitoring assertion on deb+rpm amd64; T0 egress policy test in `tests/build/`; restore rehearsal evidence row in the ledger; revocability regression test in T1. **Migrations/compat:** worker units are additive; upgraded installs get them via postinstall (mirror the pattern from `e3c2dd39`'s deb service-state fix). Backup format change is versioned in the tarball manifest; old tarballs still restore. **Rollback:** each slice independently revertible; packages carry the existing rollback wrapper. **Effect:** correctness + security + trust. **Out of scope:** agent signing/pin rotation (Phase 4), any performance work.

### Phase 2 — Instrument, reproduce navigation stickiness, baseline

#### Implementation progress (updated 2026-09-01, revised after a verification pass)

A verification pass against the checkout on 2026-09-01 found that three of these
items were checked on work that could not do what was claimed. The corrections are
recorded here rather than silently amended, because in each case the *shape* of the
mistake — an instrument reporting a clean number it had no way to measure — is the
thing worth not repeating.

- [x] Request correlation, slow-query correlation, event-loop-lag metrics, and the
  browser diagnostics/navigation ring buffer are implemented and covered.
  **Corrected:** `longTaskTotalMs` was totalled at close while the stored
  `longTasks` array kept growing (the observer callback fires after the task it
  reports), so a captured nav read `longTasks: [123ms, 122ms], longTaskTotalMs: 0`.
  §4.4 branches on "longtask >1s present". The entry now stores a copy and the
  observer stops attributing to a closed nav.
- [x] Per-chunk fetch telemetry (§4.2) now exists — it did not before. All 28 lazy
  imports go through `lib/lazyRoute.js`, which records fetch start/settle per chunk
  and retries a failed import once before the ErrorBoundary. Without it §4.4's first
  YES branch ("chunk fetch pending/failed at wedge time") was unobservable, so H1
  could only ever be reached by elimination. `tests/build/test_chunk_telemetry_contract.py`
  forbids a bare `React.lazy` from reappearing.
- [x] H5, H6, and H7 are fixed: map fallback telemetry is batched, lifecycle
  health requires consecutive failures, and map-tab loading has an error path.
- [x] The nav-critical handlers run their blocking sections off the event loop.
  **Corrected:** `get_telemetry_for_hardware` — which the new batch endpoint calls
  once per id, up to 50 — still ran two synchronous `Session` reads on the loop, so
  the batch endpoint added more on-loop database work than slice 2.5 removed. The
  old T0 test could not see it: it asserted `run_in_threadpool` appeared somewhere
  in the handler. The rule is now the absence of the thing that blocks — no direct
  `Session` call in an async nav-path function — and it covers the service function
  too.
- [x] The A/B/C load generator, safe prefix-scoped seed/cleanup, JSON result
  contract, non-blocking target evaluation, Make target, and nightly retained-
  evidence workflow are implemented. Deferred agent/telemetry axes are named in
  every result rather than silently omitted. **Corrected, three ways:** the scrape
  path was `/api/v1/metrics`, which 404s (the route is `/api/v1/metrics/metrics`,
  documented as a trap in `docs/metrics.md`), so every server-side field was null in
  every report; the `db_pool` block read two metric names the backend never
  exported, and those gauges plus a `pool_timeout` counter now exist; and the
  nightly job ran Tiers A and B only, while **both** defensible §5 targets are Tier C
  claims — it archived `applicable: false` for both, nightly. The job now runs A, B
  and C, the HTTP driver is paced to the tier's stated concurrency instead of
  hammering, WS clients verify their handshake instead of sleeping through a refused
  subscription, and `tests/build/` pins the scrape path, the tier loop, and that
  every metric read is one the backend exports.
- [x] The opt-in Chromium 6× CPU navigation harness is implemented and excluded from
  normal browser shards. **The earlier result is withdrawn.** That harness navigated
  by `history.pushState` plus a synthetic `PopStateEvent`, and located the rendered
  route as the first child `div` of `.page-content` — which is the update banner or
  the Suspense fallback whenever either is showing. Its own evidence file contained
  **no nav entry at all** for either wedged target, so the claim that both failures
  "left the requested navigation pending" was not what the data showed. The harness
  now clicks real dock `<NavLink>`s, finds the route by `[data-route-path]`, proves
  the URL moved before judging anything, and classifies each wedge into a §4.4 branch.
- [x] **Wedge reproduced and localized, 2026-09-01.** 30 navigations at 6× CPU
  throttle: **12 wedges (40%), 0 harness failures, 0 loading fallbacks.** All 12 took
  the same branch — the URL advanced through a real `navigate()` but `useLocation`
  never updated, so the route tree never re-rendered, the lazy import never started,
  and the outgoing page stayed at opacity 1. That is H1's mechanism (react-router v7
  wraps `navigate()` in `React.startTransition`; React withholds a transition's
  location update from every consumer until it can commit without a fallback),
  reached by positive evidence rather than by elimination. **Every one of the 12 was
  a navigation away from `/map`; none of the 18 navigations from other routes
  wedged** — consistent with `known_bugs` item 1's note that leaving the React Flow
  canvas is what wedges. Note that §4.4's literal H1 test ("chunk fetch pending at
  wedge time") reads *false* here, because the import never starts; the decision tree
  needs that branch added.
- [ ] Runtime baseline evidence still requires the scheduled run. The harness defects
  above mean no previously recorded baseline carries server-side numbers. The
  workflow's supported Python 3.12 environment is the source of record; its first
  `workflow_dispatch` is the evidence, and it is now capable of producing one.

**Objective:** measurement exists before optimization; the one user-visible quality symptom is root-caused and the verified adjacent defects are fixed. **Risk addressed:** flying blind; a flagship UI that feels broken.
**Findings:** F18, F12 (nav-critical subset), plus the §4 verified defects. **Complexity: M.**

| Slice | T | L | C | E | D | Notes |
|---|---|---|---|---|---|---|
| 2.1 Correlation + loop instrumentation: `X-Request-ID` middleware echoed to responses and logs; event-loop-lag gauge; expose uvicorn queue-time; axios interceptor logs request-ID + duration to a ring buffer (prod-safe mode, §4) | 4 | 4 | 5 | 2 | 5 | Prerequisite for everything measured |
| 2.2 Fleet/load simulator (F18): synthetic agents on the existing Noise test client (`tests/helpers/agent_noise_client.py`) + monitor seed + K WS browser clients; nightly non-blocking baseline job recording §5 metrics at Tiers A/B/C | 4 | 3 | 5 | 3 | 4 | Converts every "Strongly indicated" into a decision |
| 2.3 Navigation repro harness + investigation (§4): scripted journey under CPU throttle, wedge counter, evidence collection per the decision tree | 4 | 4 | 4 | 2 | 4 | Uses 2.1; runs before remediation choices |
| 2.4 Verified nav defects, fixable now (no measurement dependency): `useMapTabs` missing `.catch` (`hooks/useMapTabs.js:12-35`) — one failed `GET /maps` wedges `/map` until reload; telemetry poll vs rate limit (`useMapRealTimeUpdates.js:98-176` polls per-node against a 15/min limit in `api/telemetry.py:94` — guaranteed 429s at ≥8 nodes; fix: batch endpoint or exempt profile); health-poll 3 s abort unmounting the whole app on one slow poll (`useServerLifecycle.js:62-74` — require N consecutive failures) | 4 | 4 | 4 | 2 | 3 | These are straight bugs, Verified in code; not contingent on §4 confirmation |
| 2.5 De-async the sync-DB nav endpoints (allowed pre-measurement as correctness-preserving): convert non-awaiting `async def` handlers holding sync `Session` to `def` — start with the nav-critical set (`api/capabilities.py:24`, `api/discovery.py:220`, `api/agents.py:426`, `api/telemetry.py:96`) and move WS-handshake DB work off-loop; then the remaining ~44 as a mechanical follow-up PR | 3 | 4 | 4 | 2 | 3 | Explicitly permitted low-risk class; measure loop-lag before/after via 2.1 to quantify |

**Acceptance:** baseline dashboard exists with 2 weeks of nightly Tier A/B/C runs; wedge rate quantified before/after 2.4-2.5; loop-lag gauge shows measurable delta from 2.5 (report honestly if it doesn't). **Rollback:** all additive or mechanical; de-async conversions are one-line-per-route reverts. **Effect:** operability + latency (2.4/2.5 measured, not promised) + the evidence base for Phase 4 decisions. **Out of scope:** any remediation from §4 that its decision tree hasn't confirmed; asyncpg.

### Phase 3 — Boundary drift stopped; reliability blind spots closed

**Objective:** structural guardrails make the worst drift one-directional; background failures become visible. **Findings:** F6, F7, F13 (ratchets), F10, F9, F14, F24. **Complexity: M–L (spread over normal development, not a stop-the-world sprint).**

| Slice | T | L | C | E | D | Notes |
|---|---|---|---|---|---|---|
| 3.1 Ratchet tests (T0/T1, in `tests/build/`): direct-DB-in-`api/` count freeze (current 354), `core→services` import ban with the 12-module allowlist, `except: pass` freeze (107), token minting outside `issue_session` forbidden | 3 | 4 | 5 | 2 | 4 | Counts only go down; new code can't regress |
| 3.2 Shared WS session helper (auth handshake, caps, ping, listener); adopt in `ws_monitors` first (the divergent raw-`jwt.decode` one), then stream-by-stream; T1 contract test pins the handshake | 4 | 3 | 4 | 3 | 3 | Security-critical drift closed |
| 3.3 JetStream failure visibility (F14): max_deliver on both consumers + park-to-table `failed_messages` + an operator surface (admin page/CLI listing parked work with requeue/discard) | 4 | 3 | 4 | 3 | 3 | "At-least-once" gains explicit time bounds and visibility |
| 3.4 Lifespan/jobs decomposition (F9): extract the ~25 inline scheduler closures to `app/jobs/*.py` behind a manifest; startup phases to `app/startup/*.py`; behavior-preserving, ordering explicit; unit tests per job become possible | 2 | 3 | 4 | 4 | 2 | Largest slice; do incrementally, jobs first |
| 3.5 Throttle `receive_frame` protocol-violation writes (F24) with the existing `recordable_violation` mechanism | 3 | 2 | 2 | 1 | 1 | Tiny |

**Acceptance:** ratchet suite green in T0/T1; WS handshake contract test; a deliberately poisoned message lands in `failed_messages` and is visible + requeueable in an integration test; `main.py` line count materially down with zero behavior diffs (startup-order test). **Rollback:** per-slice reverts; job extraction keeps identical job IDs so advisory-lock semantics are unchanged. **Effect:** maintainability + reliability; no latency claims. **Out of scope:** F8 models split (deferred), full route→service migration (ratchet only).

### Phase 4 — Release operations hardened; agent supply chain; measured optimization

**Objective:** the release process defends itself; the two documented agent supply-chain risks are retired; optimization happens only where Phase 2 data says so. **Findings:** F3, F4, F17; performance items proven by baselines. **Complexity: L.**

| Slice | T | L | C | E | D | Notes |
|---|---|---|---|---|---|---|
| 4.1 TLS pin-successor rotation (F4): new additive frame delivering the next pin over the authenticated Noise channel (mirror the server-key-rotation state machine); E2E scenario: rotate cert, fleet survives | 5 | 4 | 5 | 3 | 4 | Fleet-bricking landmine; first because 4.2's rollout depends on agents surviving cert churn |
| 4.2 Agent binary signing (F3): detached signature verified by the agent before swap; **signing key lives in the release pipeline, never in the web app runtime**; enforcement feature-flagged warn→enforce across two releases; E2E: tampered binary refused | 5 | 2 | 5 | 3 | 3 | Retires the largest blast radius; rides the existing release GPG infra |
| 4.3 Chain agent authorization events (F17) into the hash-chained `Log` | 4 | 2 | 3 | 2 | 2 | Cheap once touched |
| 4.4 Performance remediation from Phase 2 data only: candidates are the §4 remediations, N+1 on measured-hot list endpoints (F20), set-based rollup/retention — each ships with its before/after benchmark from the 2.2 harness | 3 | ? | 4 | ? | 2 | L and E unknowable until baselines exist — that's the point |
| 4.5 Promote the perf gate (§5) from non-blocking baseline to blocking regression check at release tier, once 4 weeks of stable baselines + a reference hardware profile exist | 3 | 3 | 4 | 2 | 2 | Gate discipline |

**Acceptance:** E2E pin-rotation and signature-refusal scenarios in T2; ledger rows for both; every 4.4 item carries a benchmark artifact. **Rollback:** signature enforcement flag; pin rotation additive. **Out of scope:** staged fleet rollout UI, per-agent admin ACLs (both deferred until fleet sizes justify).

**Order tradeoffs, stated:** Phase 1 before instrumentation because F5/F1/F2 are contract violations needing no measurement to justify; the cost is that Phase 1 ships without new telemetry — acceptable because its acceptance criteria are binary contract tests. Agent supply-chain work lands in Phase 4 rather than 1 because both risks are documented, require design care, and their exposure scales with fleet size — but they gate remote-agent *expansion* in §7 regardless of release timing.

---

## 4. Navigation investigation plan

**Prior evidence (Verified):** `known_bugs-v1.0.0-rc.1.md` item 1 — 3 wedges/~180 navigations under CPU contention; URL advances, outgoing route stays mounted at `opacity:1`, incoming route never mounts; `AnimatePresence mode` ruled out statistically; the report's remaining suspect is the React.lazy + Suspense pair.

**New evidence, 2026-08-30 — the wedge reproduced in CI, with no CPU throttling.** CI run `33336899172` on `main` failed two independent Playwright journeys, in different browsers, with the same shape:

- `e2e/navigation.spec.ts:83` (**Firefox**) — "clicking a nav link advances the rendered page, not just the URL". `.page-content` innerHTML was still the **map page** after 10 s of polling. This spec was added by `d347fdd5`, whose message is *"encode the navigation-regression diagnostic; **bug not reproduced**"*. The diagnostic written for this bug, which previously could not reproduce it, now does.
- `e2e/agent-monitor-vantage.spec.ts:161` (**WebKit**) — every `toHaveURL` assertion for `/monitors?probe_agent_id=…` passed, and then `getByLabel('Host')` resolved to six elements, **none of them the monitor form**: they are the agent-detail page's `Host telemetry` region and discovery-scope inputs. The URL was on `/monitors`; the DOM was still `/agents/:id`.

Both failed again on retry. Neither ran under contention — these are ordinary CI runners.

**Caveats, stated rather than glossed:** the two failures share a *shape*, not a proven common cause. And the E2E job changed from a single run to two Playwright shards in `2d6368ac`, the same commit that landed the agent-fleet UI, so ordering and parallelism changed at the same time as the code did; either could be what moved the bug from rare to reproducible.

**What this changes.** Phase 2.3's job was to *build* a repro harness. Two now exist, in-tree and running on every push. The §4 decision tree can be entered against a real failing trace — each failure ships a Playwright trace, video and screenshot — instead of waiting on the throttled-journey harness. These two specs must not be quieted, retried harder, or made less strict to get CI green: they are the instrument. The route-transition machine: 150 ms exit fade → full unmount → lazy chunk fetch → mount, all 25 routes lazy behind **one shared `Suspense`** (`App.jsx:44-70,137-154`), with react-router v7 wrapping navigations in `React.startTransition` by default (`package.json:37`).

### 4.1 Ranked hypotheses

| # | Hypothesis | Status | Mechanism evidence |
|---|---|---|---|
| H1 | Router `startTransition` + lazy route suspension keeps the old page on screen with no fallback → the exact observed wedge shape | **Confirmed** (2026-09-01, 12/30 navigations at 6× throttle) | `App.jsx:44-70,137-154`; the harness records the URL advancing through a real `navigate()` while `useLocation` never updates, so the route tree never re-renders and the lazy import never starts. Note the refinement: the chunk is not *stalled*, it is never *requested* — React withholds the transition's location update from every consumer, so §4.4's "chunk fetch pending" test reads false while the mechanism is still H1's. Every observed instance was a navigation away from `/map`, matching known_bugs item 1 |
| H2 | Backend event-loop blocking makes chunk/API responses slow enough to expose H1: all request auth runs sync on the loop (`core/security.py:596-602` → per-request `db.get(AppSettings,1)` + sync Redis MGET; Redis down ⇒ full DB validation per request), plus 48 sync-Session `async def` endpoints, several on the nav path (`api/discovery.py:220` "always compute fresh", `api/capabilities.py:24`, `api/agents.py:426`), ×2 uvicorn workers | **Plausible** (pattern Verified; contribution needs runtime validation) | Matches "only reproduces under CPU contention" |
| H3 | Shell re-render storm: `useDiscoveryStream()` lives in `AppInner`, which renders Header + the whole `Routes` subtree; per-host `result_added` events and reconnect flaps re-render the mounted page including ReactFlow | **Plausible** (Verified mechanism; wedge causation unproven) | `App.jsx:81`, `useDiscoveryStream.js:100-102,246-252,316-335` |
| H4 | Main-thread blocking around `/map`: synchronous dagre layout (`utils/layouts.js:143`), ELK non-worker fallback (`vite.config.ts:41-46`), heaviest unmount on exit — known_bugs notes "navigating away from the rendered React Flow canvas is what wedges" | **Plausible** (Verified mechanism) | 8 memo sites in 3,019 lines; 27 effects |
| H5 | Perceived stickiness (not the wedge): telemetry poll fallback fires per-node against a 15/min rate limit → guaranteed 429s at ≥8 nodes; the axios interceptor sleeps `Retry-After` (5 s) and retries, holding page-state promises | **Verified defect** (independent of the wedge) | `useMapRealTimeUpdates.js:98-176`, `api/telemetry.py:94`, `client.jsx:131-135` |
| H6 | Perceived death mid-nav: one health poll exceeding its 3 s abort unmounts the entire app behind the lifecycle banner, then remounts from scratch | **Verified defect** | `useServerLifecycle.js:62-74`, `lib/constants.js:31`, `App.jsx:439-441` |
| H7 | `/map` permanent wedge: `useMapTabs` has no error path — one failed `GET /maps` leaves `loading===true` forever | **Verified defect** | `useMapTabs.js:12-35`, gate `MapPage.jsx:3002` |
| H8 | Memory growth / GC pauses (LogsPage unbounded live array `LogsPage.jsx:1022-1025`; telemetry Map copies per push) | **Unproven** | Page-scoped; low prior |

**Ruled out with evidence:** AnimatePresence mode (upstream A/B); per-navigation auth/settings refetch (providers fetch once — `SettingsContext.jsx:61-63`, `AuthContext.jsx:38-94`); rate limiting of ordinary GETs (slowapi decorates only auth/scan/mfa/telemetry; tenant limiter is pass-through); missing gzip (`nginx.mono.conf:26-32`); stale-chunk service-worker poisoning (no SW; hashed immutable assets); LoggingMiddleware on GETs (mutating-only).

### 4.2 Instrumentation

**Browser (prod-safe, always on — low overhead):**
- `performance.mark('nav:start:<path>')` on link click / `router.navigate`; `nav:end` on new route's mount effect; `PerformanceObserver` for `longtask` entries between them; ring-buffer (last 200 navigations) downloadable from the existing diagnostics surface.
- Axios interceptor already exists — add per-request `X-Request-ID` (UUID) header + duration/status into the same ring buffer.
- Chunk-load telemetry: wrap `React.lazy` in a helper that records fetch start/settle per chunk and converts a rejected import into a retry-once-then-ErrorBoundary path (this is also remediation R1's scaffold).

**Server (prod-safe):** `X-Request-ID` echo middleware into structured logs and `http_request_duration_seconds` exemplars; event-loop-lag gauge (100 ms sampler); uvicorn backlog/queue-time metric; slow-query logging ≥100 ms with request-ID.

**Deep diagnostic mode (on-demand, `CB_DIAG=1` + `CB_OTEL_ENDPOINT`):** OTel FastAPI+SQLAlchemy tracing (already built, off by default — `core/otel.py`); React Profiler build served under a flag; `pg_stat_statements` snapshot in the diagnostics bundle.

Correlation path: browser nav-ID → request-IDs issued during that navigation → server logs/spans → DB slow-query entries. WS frames tagged with connection-ID at accept time.

### 4.3 Reproducible scenario

Seed (via the Phase 2 simulator): 500 topology entities, 100 monitors @30–60 s, 10 agents, 1 discovery scan running. Client: Chrome with **6× CPU throttle**, cold cache first pass then warm. Journey (scripted, Playwright): login → `/map` (wait for canvas) → `/monitors` → `/map` → `/agents` → `/settings` → back to `/map`; repeat ×30 (≈180 navigations, matching the known_bugs sample size); count wedges (URL≠rendered route for >5 s), record nav ring buffer + server metrics. Run 3 variants: baseline; with Redis stopped (H2/H5 amplifier); with backend under `stress-ng --cpu 2` (contention).

### 4.4 Profiling decision tree

```
Wedge reproduced?
├─ NO (after 500+ navigations) → symptom is perceived latency, not the wedge:
│   check nav ring buffer p95 → dominated by API time? → server side (below)
│                              → dominated by longtasks? → H4: profile /map unmount + dagre
├─ YES → inspect the wedged navigation's ring buffer entry:
│   ├─ NO nav entry for the target, but the URL advanced → the router's location
│   │   update never reached useLocation: H1 CONFIRMED (this is the branch all 12
│   │   observed wedges took on 2026-09-01; the lazy import never starts, so the
│   │   chunk test below reads false) → R1
│   ├─ chunk fetch pending/failed at wedge time → H1 CONFIRMED → R1
│   ├─ chunk resolved, mount never ran, longtask >1s present → H4 → R4
│   ├─ chunk resolved, React committed but old tree visible → framer-motion exit
│   │   never completed → re-open the AnimatePresence question with the new data
│   └─ all requests slow (>2s) at wedge time → server side:
│       ├─ loop-lag gauge elevated → H2 CONFIRMED → R2 (verify: which endpoint held
│       │   the loop — match request-IDs to slow routes; sync-session async defs first)
│       ├─ loop-lag normal, DB slow-query hits → query problem (F20 path), not H2
│       └─ 429s in buffer → H5 → R3
└─ App unmounted entirely during nav (banner flash in trace) → H6 → R5
Discovery scan running during wedges but not otherwise → H3 → R4b
```

### 4.5 Remediations (max five; each contingent on its confirmation, except the verified defects)

| R | Contingent on | Change |
|---|---|---|
| R1 | H1 | Per-route `Suspense` fallback (skeleton) inside the transition wrapper so a suspending chunk shows progress instead of freezing the old page; chunk-retry + ErrorBoundary on rejected imports; idle-time prefetch of the 3 heaviest chunks after first paint. If evidence shows `startTransition` itself is load-bearing in the wedge, opt out via router future-flag — only then |
| R2 | H2 | Ship the rest of F12 de-asyncing beyond the Phase 2.5 nav set; move the per-request `AppSettings` read behind the existing 10 s cache and make the session-cache Redis call non-blocking on the loop |
| R3 | H5 (already Verified) | Batch telemetry endpoint (one request for N nodes) or move the map fallback poll to a limiter profile sized to node count; remove the silent `Retry-After` sleep for background polls |
| R4 | H4 (a: layout) / H3 (b: shell) | a: run dagre/ELK in a Web Worker (ELK worker mode exists; fix the vite fallback), defer heavy teardown with `startTransition` on exit; b: move `useDiscoveryStream` below the route tree into a context consumed only by the pages that need it, batch `result_added` updates |
| R5 | H6 (already Verified) | Health-poll: require 3 consecutive failures (or 1 failure + 1 confirmatory with backoff) before flipping to offline; never unmount the route tree for a degraded banner |

H7 (`useMapTabs` `.catch`) is fixed unconditionally in Phase 2.4 — it is a one-line bug, not a remediation candidate.

---

## 5. Performance and capacity plan

### Workload matrix

| Tier | Agents | Monitors (interval) | Browser users / WS clients | Topology entities | Telemetry rate | Deployment modes measured |
|---|---|---|---|---|---|---|
| A "Starter" | 2 | 10 @60 s | 1 / 2 | 25 | 2 agents ×30 s heartbeat | mono Docker |
| B "Enthusiast" | 10 | 50 @30–60 s | 2 / 5 | 150 | 10 ×30 s + hardware polls | mono Docker, native systemd |
| C "Advanced" | 50 | 200 @30 s | 5 / 10 | 500 | 50 ×30 s + retention active | all three (packaged once F5 lands) |
| D "Stretch" (informational, not a support claim) | 250 | 500 @30 s | 5 / 15 | 1,000 | 250 ×30 s | mono Docker |

Reference hardware profile to be defined from real operator reports (start: 4 vCPU / 8 GB, the common Proxmox VM shape). Retention/rollup jobs run during the measurement window at Tiers C/D — the 02:00–03:45 job cluster is part of the workload, not noise.

### Measured per tier

p50/p95/p99 per route (`http_request_duration_seconds`, exemplar-linked); event-loop lag p95/p99; query count + time per request (OTel spans, deep mode); DB pool utilization + `pool_timeout` events; Redis connections (vs 250 cap) and memory; JetStream consumer lag + queue depth/age for MONITOR_POLL/TELEMETRY; monitor-due backlog/lag gauges (already exported, `api/metrics.py:94-140`); WS fanout latency (publish→client receive, sampled); browser long-task count + nav p95 from the §4 ring buffer; process CPU/RSS/disk I/O; error and retry rates (axios retry counter, nak counts).

### Targets

Only the two defensible ones, until baselines justify more:
1. **Monitor scheduling lag < the shortest supported poll interval** at Tier C, sustained through the nightly job window.
2. **Topology-load p95 < ~2 s at 500 entities** (Tier C), measured server-side + browser-side.

Everything else: collect 4 weeks of nightly baselines (Phase 2.2), then set regression thresholds as *change* limits (e.g., p95 within +20% of trailing baseline) rather than invented absolutes.

### Release performance gate

Stage 1 (immediately after Phase 2.2): nightly non-blocking baseline job, results archived as ledger evidence. Stage 2 (Phase 4.5, after ≥4 weeks stable + reference profile defined): blocking at release tier — a release candidate that regresses the two product targets or exceeds the change limits fails T3-adjacent verification with the same evidence discipline ADR 0005 already mandates.

---

## 6. Guardrails and production gates

| Gate | Signal | Cost | False-positive risk | Tier | Owner area |
|---|---|---|---|---|---|
| Egress policy test: no `httpx`/`requests` construction outside `core/egress.py` (frozen allowlist) | New unguarded outbound call = fail | seconds (AST grep) | Low; allowlist edits are deliberate | T0 | backend |
| Dependency-direction ratchets: `core→services` ban (12-module allowlist), direct-DB-in-`api/` count ≤354 and monotonically ratcheted down, `except: pass` ≤107 | Boundary drift | seconds | Low; counts only ever tighten | T0 | backend |
| Token-issuer ratchet: `create_token`/`_make_token` callable only from `issue_session` (allowlist: agent/service-account paths) | New unrevocable-token path | seconds | Low | T0 | backend |
| Package contract: Tier 3 exercise step asserts a monitor sample lands on deb/rpm installs; worker units enabled post-install and post-upgrade | Supported install silently loses monitoring | minutes (already-running VMs) | Low; flake mitigated by 2× interval wait | T3 (pre-release/nightly) | packaging |
| Upgrade/rollback compatibility: existing Phase 3 rows + this release recorded as the first real N-1 fixture; migration reversibility spot-check per release | Broken upgrades | already paid | Medium (VM flake) — ADR 0005 evidence rules apply | T3 | packaging |
| WS handshake contract test: shared helper's auth sequence pinned; all five streams must use it | Divergent WS auth | seconds–minutes | Low | T1 | backend |
| Agent protocol conformance (exists — frame/scope/rekey corpora): extend for every new frame (pin-successor, signature metadata) | Cross-language drift | already paid | Low | T1/T2 | agent |
| Backup restore + encryption verification: Tier 3 creates an encrypted snapshot, restores it into a fresh install, asserts app boots + a known record survives + tarball contains no plaintext `vault.key` | Unrestorable/leaky backups | minutes | Low | T3 | backend/packaging |
| Signed-update E2E: tampered agent binary refused; pin-rotation E2E: cert regenerated, fleet reconnects | Supply-chain regression | minutes (Docker E2E exists) | Low | T2 | agent |
| Perf gate: §5 two targets + change limits | Perf regression | ~15 min nightly | **Medium-high initially** — hence non-blocking until baselines stabilize | nightly → release | backend |
| Release checklist (hard stops): all T0–T3 green with evidence hashes; ledger has no `not_evidenced` blocker rows; restore rehearsal done; changelog + rollback instructions published; no open B1–B6 condition | Process bypass | minutes | n/a | release | release owner |

---

## 7. Definition of done

### Required before calling the release production-ready
- [ ] B1–B4 and B6 closed (Phase 1 complete; Tier 3 monitoring **and** encrypted-restore assertions green on deb + rpm amd64, against CI-built artifacts).
- [ ] ~~ADR 0005 platform Tier 1 marked **in force** with evidence~~ — **corrected**: Tier 1 cannot be in force at 0.4.0 (see B5). What is required at this release is that 0.4.0 is recorded as the N-1 upgrade fixture for the next, with its artifacts and digests retained, and that the ADR table says so instead of staying silent.
- [x] Egress and token-issuer ratchet gates active in T0 (`tests/build/test_phase1_policy_ratchets.py`). The **dependency-direction** ratchets are Phase 3.1 and are not a Phase 1 deliverable — they were folded into this line by mistake when the DoD was drafted.
- [ ] Backup restore rehearsal (encrypted) evidenced in the ledger. *Assertion implemented and gated (`t3::exercise_encrypted_snapshot_roundtrip`, `tests/build/test_encrypted_backup_contract.py`); the ledger row needs the Tier 3 run against CI artifacts.*
- [ ] Instrumentation from Phase 2.1 shipped (request IDs, loop-lag, nav ring buffer) — production-safe mode only.
- [ ] The three Verified navigation defects fixed (H5 429s, H6 whole-app unmount, H7 `/map` wedge) and the §4 harness run recorded, with wedge rate published in release notes if nonzero.
- [ ] Release checklist executed with hard stops; rollback instructions tested on a VM, not just written.

### Required before expanding remote-agent use beyond a tightly supervised environment
- [ ] F4 pin-successor rotation shipped + E2E (cert regeneration must not strand agents).
- [ ] F3 signed agent updates at least in warn mode, enforce date announced; signing key held outside the app runtime.
- [ ] F17 agent authorization events in the hash-chained audit log.
- [ ] F24 violation-write throttling.
- [ ] Documented recovery runbook: compromised-agent revocation, server-key rotation, Redis-outage behavior (F16) stated plainly to operators.

### Valuable follow-up that must not delay the release
- Phase 3.4 lifespan decomposition beyond the first job batch; F8 models split; F22 MapPage decomposition (do alongside R4a if H4 confirms); F23 `response_model` ratchet; F15 CSP nonces; F21 hygiene sweep; remaining F12 conversions beyond the nav set; F20 N+1 fixes that baselines don't flag as hot; staged fleet updates; Tier D characterization.

---

## 8. Phase 1 closeout — what is done, and the handoff

**State at this commit.** Every Phase 1 slice (1.1–1.7) is implemented and gated. `make verify`
(Tier 0 + Tier 1, including the security gate) is green; the repo-policy suite is at 513 tests.
The T0 ratchets that keep the promises from drifting are `tests/build/test_phase1_policy_ratchets.py`
(egress choke point, single token issuer, retired JWT login router, worker inventory, air-gap DNS
ordering) and `tests/build/test_encrypted_backup_contract.py` (the `age` dependency, one encryptor,
both restore paths refusing a `.age` without an identity, and the Tier 3 round trip being called
rather than merely defined).

**Why this cannot be finished from a workstation.** `tier3-artifact.sh` refuses to treat a locally
built package as evidence, deliberately: a PyInstaller bundle inherits its build host's glibc floor,
so a package built on Fedora 44 demands `GLIBC_2.38` and cannot run on Debian 12 at all — which is
exactly how the `debian-deb-amd64` row failed once already (ADR 0005 Phase 3, F8). Only the release
job's ubuntu-22.04 build carries the 2.35 floor every supported distro clears, and only it stamps
`built_by=ci` in `build-info.json`. The four fleet runs in `artifacts/diagnostics/` are development
checks against local builds; they also predate both the scheduled-monitor and the encrypted-backup
assertions, so they evidence neither B1 nor B3 even setting provenance aside.

### The remaining steps, in order

1. **Tag and push `v0.4.0`.** `make release-tag && git push origin v0.4.0`. This is yours to run: it
   publishes a GitHub Release and pushes images to GHCR. `.github/workflows/release.yml` asserts
   version parity against `VERSION` before it builds anything.
2. **Fetch the published artifacts** — the deb, the rpm, the companion `circuit-breaker-nats`
   **rpm and deb**, and `SHA256SUMS` — into one directory, and verify the sums. `dispatch.sh` picks
   the companion up from the candidate's own directory, so they must land together.

   *Note the deb companion is new as of the v0.4.0 release attempt.* The application deb depended on
   a bare `nats-server`, which Ubuntu 22.04 does not package, so the deb was uninstallable on a
   current Ubuntu LTS and the release stopped at Artifact Smoke. The dependency is now
   `nats-server | circuit-breaker-nats` and the companion is built for both packagers. One
   consequence for Tier 3: the `debian-deb-amd64` rows will now be handed a companion deb and will
   install **our** broker rather than Debian's, because apt prefers what it is given on the command
   line. That is the configuration the release ships, so it is the right thing to test — but it means
   the row no longer exercises "the distro's nats-server satisfies the dependency". Ubuntu 24.04 and
   Debian 12 still resolve to the distro package for a user installing the application deb alone.
3. **Run the two `mode: install` rows against those artifacts** (needs local QEMU; nothing in CI runs
   Tier 3):
   ```
   make verify-fleet CB_ROW=fedora-rpm-amd64 CB_CANDIDATE=<dir>/circuit-breaker_0.4.0_amd64.rpm
   make verify-fleet CB_ROW=debian-deb-amd64 CB_CANDIDATE=<dir>/circuit-breaker_0.4.0_amd64.deb
   ```
   Do **not** pass `CB_ALLOW_LOCAL_CANDIDATE=1`. Each row now asserts, on top of install/boot:
   a scheduled TCP monitor produces an `avail` sample within 20 s (**B1**), and an encrypted snapshot
   is created, proven opaque, and restored with a known record surviving (**B3**). Evidence lands in
   `artifacts/diagnostics/tier3-<row>/`; the new files are `monitor-*.json`, `worker-units-*.txt`,
   `encrypted-snapshot*.txt`, `encrypted-restore*.txt`, and `build-info-candidate.json` should read
   `"built_by": "ci"` with no `development-run` line beside it.
4. **Record the ledger rows** with the artifact digests and evidence hashes, per
   `specs/1.0.0/release-control/evidence-and-invalidation.md`:
   - `SRV-02` (worker ownership) — the monitoring assertion is what backs it.
   - `ACC-01` (fresh native install) — the install rows.
   - `ACC-14` (backup and restore) closes only **partially**: the Tier 3 rehearsal restores into the
     same host, not a clean one, and takes the snapshot idle rather than under load. Record what was
     actually exercised and leave the clean-host and under-load clauses open rather than promoting
     the row on a narrower run than it names.
5. **Annotate ADR 0005's tier table** rather than flipping it. Tier 1 stays *not in force*; the row
   should say that 0.4.0 is the first release whose package boots, that it is retained as the N-1
   fixture, and that Tier 1's evidence arrives at `0.4.0 → 0.5.0`. Silence there reads as an
   oversight; the annotation is the finding.
6. **Retain the 0.4.0 artifacts and their digests** somewhere the 0.5.0 upgrade rows can reach them.
   This is the single most valuable output of this release, and it is lost by default.

### Open, and deliberately not done here

- **A Tier 1 round trip through the real `age` binary.** `age` is not installed on this workstation
  and is not in the CI test image, so the round trip lives at Tier 3, where the package's own
  dependency guarantees it. The Tier 0 contract test pins the dependency so it cannot vanish. If
  `age` is added to the CI image, an unstubbed round-trip test at Tier 1 would be cheap and worth
  having — the current unit tests all stub `subprocess.run`.
- **`cb backup --encrypt-to` in `docker`/`compose` mode is implemented but only exercised statically.**
  The Tier 3 rows are package installs; the container path is asserted by
  `test_the_shell_never_encrypts_on_its_own` and by the `docker exec` data-dir gate, not by a run.
- **Phase 3.1's dependency-direction ratchets** (`core→services`, direct-DB-in-`api/`, `except: pass`)
  are still Phase 3, despite §7 having listed them beside the Phase 1 gates.

---

**Decision recommendation.** Start Phase 1 immediately — it is small, binary, and every slice defends a promise users already rely on; slice 1.1+1.2 (packaged monitor workers + the Tier 3 assertion) is the first PR train, because it converts the product's largest silent contract violation into a permanently-tested guarantee and unblocks calling deb/rpm a supported topology at all. Phase 2 starts as soon as 1.1 merges (they don't conflict), so that by the time Phase 1 closes, the navigation symptom is quantified and the baseline program is running — and every decision after that point is made on measurement rather than instinct.
