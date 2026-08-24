# Circuit Breaker 2.0 — Posture Engine Design

**Date:** 2026-08-23
**Status:** Approved for planning
**Baseline:** `91944b73` (`dev`), `VERSION` = `1.0.0-rc.3`
**Supersedes:** nothing. Extends the privacy-scoring subsystem introduced pre-1.0.

---

## 1. Context

Circuit Breaker 1.0 documents and visualises infrastructure. It also carries several
security-adjacent subsystems that are either shallow or unreachable:

| Subsystem | State at 1.0 |
|---|---|
| Privacy scoring (`services/privacy_rules.py`) | 7 rules, all port-presence, one fact source, has a UI |
| CVE ingestion (`services/cve_service.py`) | Full NVD 2.0 pipeline into `data/cve.db`; surfaced only via `VulnerabilityPanel.jsx` |
| Business intelligence (`services/intelligence/`) | Blast radius, capacity forecast, efficiency — computed, scheduled, **no UI** (INC-10) |
| Knowledge base (`api/kb.py`) | OUI/hostname CRUD feeding discovery naming — **no UI, no docs** (INC-11) |
| Audit chain (`api/admin_audit.py`) | Tamper-evident, verify/repair implemented — **no UI** (INC-12) |

The limiting factor is not rule count. It is that **a finding has no identity**.
`NetworkPrivacySnapshot.deductions` is `JSONB`, recomputed wholesale at scan-finalize
(`services/discovery_service.py:1177`). A finding exists only as an element inside a blob that
gets replaced. It therefore cannot have a first-seen date, a history, a disposition, or a
verified fix.

This is why drift is impossible today, why "a problem you fixed came back" is unrepresentable,
and why the score can only ever describe this instant.

## 2. Goals

1. Findings become durable, identified records with a lifecycle.
2. Posture draws on structurally different fact sources, not one port scan.
3. The operator can see their perimeter from outside it.
4. Every finding carries a path to a fix, and the fix can be verified.
5. Severity reflects what a finding actually threatens.

## 3. Non-goals

- **Assisted or automated remediation.** The agent does not execute fixes. This was considered
  and declined: it would make `cb-agent` a privileged execution surface, which is a different
  product decision than this release makes.
- **Project-operated cloud services.** No hosted scanner, no phone-home for remediation content.
- **Multi-tenancy.** ADR-0003 stands.
- **Compliance frameworks.** No CIS/NIST mapping in 2.0.

## 4. Release cut

2.0 ships the engine plus **two** structurally different fact sources. Two is the minimum that
proves a plugin seam; one is that source with extra indirection.

**In 2.0:** posture engine · `network_scan` migration · `host_posture` agent capability ·
`egress_probe` scope mode and the Exposure surface · scoring v2 · remediation cards · recheck ·
drift · vulnerabilities.

**Deferred to 2.1:** config-digest fingerprinting · credentialed appliance posture (Proxmox,
OPNsense, UniFi, TrueNAS) · additional probe targets behind a challenge protocol · posture as a
map lens · perimeter diagram.

Rejected: shipping all four fact sources at once. `docs/1.0.0-incomplete-features.md` is a
20-item record of what half-built subsystems cost; repeating that at four-source scale is the
predictable failure of this release.

## 5. Architecture — the posture engine

### 5.1 Finding identity

New table `posture_findings`, one row per stable key:

```
(ruleset, rule_id, subject_type, subject_id, discriminator)
```

`discriminator` distinguishes findings that share a rule and a subject — unexpected exposure on
tcp/8080 and tcp/32400 on one host are two findings, not one that flickers between values.

Columns beyond the key: `status` (`open` | `resolved` | `suppressed`), `severity`, `base_points`,
`first_seen_at`, `last_seen_at`, `resolved_at`, `last_evaluated_at`, `source`, `evidence` (JSONB).

This pattern already exists in the codebase and is proven under agent outage:
`ScanResult.finding_id` is "a digest of dispatch/kind/address," replay-stable by construction,
backed by the partial unique index `uq_scan_results_job_finding` used as an idempotency key.

### 5.2 FactBundle

```
FactBundle(source, observed_at, coverage, facts)
```

Sources emit bundles onto an ingest path rather than calling the engine inline. The three sources
run on unrelated clocks — scan-finalize is event-driven, host posture pushes on the agent's own
interval, appliance pulls (2.1) are scheduled — and inline evaluation would couple engine latency
to the slowest source.

`coverage` declares **what the source examined**, independent of what it found. It is an explicit
field and is never inferred from `facts`.

### 5.3 Reconciliation

Rulesets turn `facts` into asserted finding keys. The engine diffs asserted keys against open
findings **within `coverage`**:

| Case | Action |
|---|---|
| asserted, no open row | insert; `first_seen_at` = now; emit `opened` |
| asserted, open row exists | bump `last_seen_at` |
| asserted, row is `resolved` | reopen; emit `reopened` |
| not asserted, inside `coverage` | resolve; stamp `resolved_at`; emit `resolved` |
| not asserted, outside `coverage` | leave untouched |

**The last row carries the security weight of this design.** Without explicit coverage, a source
that fails or an agent that drops offline reads as "every finding it was proving has been fixed,"
and the score leaps to an A on the strength of a failed scan. That is the same failure class as
INC-03: wrong, invisible, and wrong in the dangerous direction.

### 5.4 Derived snapshots

`NetworkPrivacySnapshot` survives as a rollup computed *from* findings, feeding the existing
history chart. It stops being the system of record.

`PrivacyFindingIgnore` folds into `status = suppressed` plus suppression metadata on the row.

**Recommendation carried forward, not adopted:** suppression should require an expiry that
reopens the finding. `PrivacyFindingIgnore` is a permanent mute today, which is the mechanism by
which every long-running posture score decays into noise nobody reads. Product declined this for
2.0; it is recorded here because the cost of adding it later is a migration over live
suppressions.

## 6. Fact sources

### 6.1 `network_scan` — migration, not new capability

Scan-finalize stops calling `recompute_all(db)` and emits a bundle with `coverage` = the
addresses the job actually swept. The existing 7 rules move across unchanged as the
`network_exposure` ruleset.

Deliberately behaviour-preserving: validated by asserting the engine produces the same findings
the current implementation does for the same scan input. This is the cheapest available proof
that the new abstraction is faithful.

### 6.2 `host_posture` — new agent capability

One entry in `CAPABILITY_DEFINITIONS` (`services/agent_capabilities.py`), one in the Go
`configNormalizers` mirror (`apps/agent/internal/capability`), per that module's stated contract:
*"A new slice adds exactly one entry here and one there, and touches nothing else."*

Collected facts: listening sockets **with owning process**, host firewall rules
(nftables/iptables/ufw), OS and package inventory, sshd configuration facts, Docker images and
published ports. `coverage` = the host itself.

Sub-toggles follow the `include_docker` precedent and every one defaults **off**:
`include_listening_sockets`, `include_firewall`, `include_packages`, `include_ssh_config`.

`default_enabled: False` is load-bearing. The registry guarantees `default_enabled` is consulted
only by `approve_agent` at first grant-write, with no backfill permitted, pinned by
`test_new_registry_entry_is_not_backfilled_onto_already_approved_agents`. **Upgrading to 2.0 must
not silently enable security-configuration reading on an already-approved agent.** That test
becomes materially more important than when it was written and must not be deleted.

### 6.3 `egress_probe` — new scope mode

A second member of `SCOPE_MODES` in `core/agent_scope.py`, with rules inverted relative to
`direct_private`: rather than deriving an allow-set from attached interfaces, it permits exactly
one destination and denies all others. Special-use denial continues to run before any allow rule,
unchanged.

**Ownership model: an agent may only probe the address it is already connected to.**

The probe agent reaches the server via `server_url` from `/etc/circuit-breaker/agent.toml`. That
endpoint *is* the operator's public address. Resolve it, pin it, allow it and nothing else.

The consequence is that this feature cannot scan an arbitrary target even in principle — only the
host it already holds an authenticated Noise session with. There is no ownership challenge to get
wrong, because connectivity is the proof. Additional targets (second WAN, IPv6 prefix, alternate
DDNS name) require a DNS-TXT or well-known-path challenge and are deferred to 2.1.

Both implementations change together — Python `core/agent_scope.py`, Go
`apps/agent/internal/netscope` — with `fixtures/agent_scope_corpus.json` extended to cover the new
mode. The corpus is what keeps the two honest and is not optional for this slice.

**New concept: `external` placement on an agent.** A probe agent's derived `direct_private` scope
is meaningless — it sits on a VPS, not the operator's LAN — and local discovery must never run
against a rented host's neighbours. Placement is a property of an existing agent, not a new agent
type.

## 7. Scoring

Shape is preserved: 0–100, `PRIVACY_GRADE_BANDS` A–F, same history series. Existing chart history
stays meaningful and the grading needs no reinvention.

```
points = base_points × criticality × exposure
```

**Criticality** derives from `calculate_blast_radius` (`services/intelligence/dependency_graph.py`).
`PRIVACY_GATEWAY_POINTS_MULTIPLIER = 1.5` is retained as a **floor**, not replaced: a gateway
matters for reasons that outlive its documented dependency count, and a lab with little
downstream documentation must not de-rank its router to nothing.

`_build_adjacency` is a whole-DB single-pass build, so criticality is computed **once per
evaluation run** into an `asset_criticality` cache (value + `computed_at`) that findings read.
Per-finding calls would rebuild the graph per finding. This also gives the `analytics_job`
scheduler cost a consumer, which INC-10 correctly notes it currently lacks.

**Exposure** multiplies findings that `egress_probe` confirmed reachable from the internet above
identical findings on internal-only subjects. Confirmed-reachable is now a fact rather than an
assumption.

Existing bounds (`PRIVACY_DEVICE_AGGREGATE_TOP_N`, `PRIVACY_DEVICE_AGGREGATE_CAP`,
`PRIVACY_CRITICAL_CHECK_CEILING`) survive and clamp the result.

**Staleness is part of the score.** Coverage tells the engine which sources reported and when. A
source silent past its expected interval renders the score as stale with a named reason. A score
that improves because an agent died is worse than no score.

**Scoring version boundary.** v2 produces different numbers from v1 on identical infrastructure.
`scoring_version` is stamped on the snapshot row and the history chart draws a visible break at
the boundary rather than presenting a continuous series. Cheap now; impossible to retrofit once
users have filed bugs about their grade dropping on upgrade day.

## 8. Surfaces

Navigation: `Posture` → `Overview` / `Exposure` / `Vulnerabilities` / `Drift`. A sidebar group
with real pages, so each surface deep-links, and Exposure is visible without a click.

### 8.1 Exposure — reconciliation

The page diffs what the probe found against what inventory says is published, into four buckets:

| Bucket | Meaning |
|---|---|
| **Untriaged** | Answering, intent never declared |
| **Unexpected** | Answering, declared internal |
| **Intended but unreachable** | Declared public, no answer — broken forward or dead service |
| **Confirmed as intended** | Declared public, answering |

This is the one view no competing tool can build, because it requires knowing what the operator
*meant* to publish. The third bucket is a second feature at no extra cost: nothing in the product
currently detects a port forward that silently broke.

**Intent is three-state** — `public` | `internal` | `undeclared` — on services, defaulting to
`undeclared`. An undeclared service that answers is *untriaged*, not accused. Upgrade day opens on
"12 services need intent declared," a task with an end, rather than 12 red findings that are
probably fine. Undeclared subjects contribute nothing to the score until intent is stated.

### 8.2 Remediation cards

`remediation_id` — already threaded through `privacy_rules.py` with nothing on the other end —
resolves to a content module versioned in-repo and never fetched at runtime. A posture tool that
phones home for remediation text contradicts the product's positioning.

Rendering substitutes what is known about this subject: host, port, detected OS, package version,
and where `host_posture` identified the package manager, a concrete command rather than generic
prose. Cards can link a user's own Note or runbook so house procedure supersedes canned text.

### 8.3 Recheck

A targeted re-run of exactly one fact source scoped to one subject, producing a `FactBundle` with
`coverage` = that subject alone. The engine reconciles it like any other bundle — there is no
separate verification path that could disagree with normal evaluation. Reuses existing on-demand
dispatch.

Requires per-subject rate limiting and an honest disabled state when the probe agent is offline,
which is a real case for `egress_probe`: it runs on a VPS the operator pays for and may destroy.

### 8.4 Drift and Vulnerabilities

**Drift** reads finding transitions off the lifecycle — `opened` / `reopened` / `resolved` with
timestamps. Nothing new is computed. Config-digest drift joins it in 2.1.

**Vulnerabilities** is package inventory × `cve.db`, plus an EOL feed. This gives the CVE
subsystem a front door.

**Entity detail pages** gain a findings panel; `VulnerabilityPanel.jsx` generalises into it rather
than a second component being written beside it.

## 9. Error handling and failure modes

| Failure | Required behaviour |
|---|---|
| Fact source errors mid-run | Bundle is discarded entirely. Partial coverage must never reconcile — a half-finished scan would resolve findings it never re-examined. |
| Agent offline | Findings it proved remain open and are marked stale. Never resolved. |
| Probe agent destroyed | Exposure surface renders last-known with age, plus an explicit "no probe" state. Score marks the exposure dimension unmeasured, not clean. |
| Blast-radius computation fails | Criticality falls back to 1.0 (gateway floor still applies). Scoring proceeds degraded rather than blocking. |
| CVE database unavailable | Vulnerability findings hold last state and mark stale. No resolution. |
| Ruleset raises on one subject | That subject drops out of `coverage` for the run. It is not silently treated as clean. |

The invariant across every row: **absence of evidence never resolves a finding.**

## 10. Testing strategy

- **Reconciliation** is pure given a bundle and prior state — property tests over generated
  bundle sequences, asserting no path resolves a finding outside coverage.
- **Migration fidelity** — the `network_exposure` ruleset must produce findings identical to
  current `privacy_rules.py` output over a fixture corpus of scan results.
- **Scope corpus** — `fixtures/agent_scope_corpus.json` extended for `egress_probe`, exercised by
  both the Python evaluator and the Go mirror. Cases must include: the permitted self-target;
  a non-server public address (deny); loopback, link-local and cloud-metadata via the new mode
  (deny, special-use first); a rebinding resolver returning one permitted and one forbidden
  address (deny).
- **Capability non-backfill** — `test_new_registry_entry_is_not_backfilled_onto_already_approved_agents`
  extended to cover `host_posture` explicitly.
- **Staleness** — an agent going silent must not raise the score. Direct regression test.
- **Scoring bounds** — multipliers composed at extremes stay inside `PRIVACY_MIN_SCORE` /
  `PRIVACY_MAX_SCORE`.
- `notify_email` currently has no coverage anywhere in `apps/backend/tests` (INC-02). Posture
  alerting must not extend that pattern.

## 11. Prerequisites

**INC-03 is a hard prerequisite, not parallel work.** Posture transitions route through the
existing notification system, which compares `route.alert_severity == severity`
(`workers/notification_worker.py:224-225`) behind a UI labelled "Minimum Severity." A route set to
`warning` silently drops every *critical* posture finding. Shipping posture alerting on that
foundation means shipping a security product whose alarms do not fire.

**INC-06 should precede it.** Posture alerts carry findings such as "telnet exposed on the
gateway" into sink payloads, and `NotificationSink.provider_config` is plaintext JSONB readable by
any `viewer` (`api/notifications.py:95-99`). A low-severity issue at 1.0 becomes a meaningfully
worse one when the payloads describe the operator's weaknesses.

Neither is inside 2.0's scope. Both sequence ahead of it.

## 12. Incomplete-feature register interaction

This release retires several 1.0 gaps by giving the subsystems a job, rather than by building
obligatory UIs:

| ID | Interaction |
|---|---|
| INC-10 | Blast radius becomes the criticality multiplier; `analytics_job` gains a consumer |
| INC-11 | KB OUI/hostname tables become the device identification that vendor-risk matching depends on |
| — | The CVE subsystem is not in the register at all, having a panel and therefore a surface. It nonetheless gains the Vulnerabilities page and, via `host_posture` package inventory, matching that is evidence-based rather than inferred from a vendor string |
| INC-03, INC-06 | Promoted to prerequisites (§11) |
| INC-12 | Untouched. Audit-chain UI belongs to the evidence pillar, which was explicitly not selected |

## 13. Open questions

1. **Suppression expiry** — declined for 2.0 (§5.4). Revisit before the first release that
   accumulates a year of findings.
2. **EOL feed source** — `endoflife.date` is the obvious candidate but adds a runtime external
   dependency, which sits awkwardly beside §6's no-phone-home stance. Options: vendored periodic
   snapshot, or opt-in fetch. **Undecided; must be resolved before the Vulnerabilities slice.**
3. **Intent on non-service subjects** — hardware and compute units can also expose ports. 2.0
   declares intent on services only; whether the other two need it is deferred until the Exposure
   page has real usage.

## 14. Implementation slices

This design is deliberately larger than one implementation plan. It decomposes into slices that
each land independently, in this order:

| # | Slice | Depends on | Notes |
|---|---|---|---|
| 1 | Engine core + `network_scan` migration | INC-03 fixed | `posture_findings`, `FactBundle`, reconciliation, derived snapshots. Behaviour-preserving: same findings out as today. |
| 2 | Scoring v2 | 1 | Criticality cache, staleness, `scoring_version` boundary. Exposure multiplier present but fixed at 1.0 until slice 4. |
| 3 | `host_posture` capability | 1 | Python registry entry, Go collector, host ruleset. Lower risk than slice 4 and proves the plugin seam first. |
| 4 | `egress_probe` scope mode | 1 | Python + Go + corpus, `external` placement, probe dispatch. The delicate slice; it gets its own review. |
| 5 | Exposure surface | 4 | Intent tri-state on services, triage flow, reconciliation buckets. Activates the exposure multiplier from slice 2. |
| 6 | Remediation cards + recheck | 3, 5 | Content modules, targeted single-subject re-runs. |
| 7 | Vulnerabilities page | 3 | Package inventory × `cve.db` is unblocked; only the EOL half waits on open question 2. |
| 8 | Drift page + posture alerting | 1, INC-03 | Transitions are already recorded by slice 1; this surfaces and routes them. |

Slices 3 and 4 are independent of each other and may run in parallel. Slice 1 gates everything.
