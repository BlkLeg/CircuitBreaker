# Feature gap assessment en route to 1.0

**Date:** 2026-09-05 · **Head:** `dev` @ `e48db3ae` · **Audience:** homelab first, SMB next
**Method:** code-level audit of the monitoring/alerting, tenancy/RBAC, discovery/intelligence, and
frontend/API/ops subsystems. Every claim below cites source or names the grep that established
absence. This supersedes the first draft of this document, which was written without reading the
codebase and recommended nine features that already ship.

---

## 1. Corrections to the previous assessment

Nine of the fifteen recommendations in the prior draft are already built. Recommending them again
would have spent a release cycle rebuilding shipped features.

| Prior recommendation | Actual state |
|---|---|
| Dependency mapping / blast radius | **Ships.** `services/intelligence/dependency_graph.py` builds adjacency from hardware links, shared networks, compute parentage, service dependencies and storage; `calculate_blast_radius()` is a downstream BFS; `GET /intel/blast-radius/{type}/{id}`; `BlastRadiusPanel` is mounted in the hardware, compute, service and storage drawers. |
| Alerting engine with Discord/Slack | **Ships.** Slack, Discord, Teams and email sinks with severity-floor routing, Fernet-encrypted webhook URLs, Redis dedup, retry with backoff and a JetStream dead-letter path (`workers/notification_worker.py`). Gotify, ntfy, PagerDuty and a generic webhook are the real absences. |
| Container discovery | **Ships for Docker.** `services/docker_discovery.py` creates `Network` and `Service` rows; the Go agent has an opt-in `host.docker` collector. Kubernetes and Podman are absent. |
| CVE scanning against NVD | **Ships, with real defects.** NVD 2.0 → local SQLite (`services/cve_service.py`, `db/cve_session.py`), surfaced in `VulnerabilityPanel`. See §2.5 — the matching is unsound and it cannot refresh air-gapped. |
| LLDP automation | **Ships.** SNMP LLDP-MIB walk (`services/discovery_probes.py:433`), stored on `scan_results.lldp_neighbors_json`, applied through `LLDPReviewModal` to create `HardwareConnection` rows. CDP and bridge/MAC-table discovery are absent. |
| Auto-arrange / force-directed layout | **Ships, extensively.** Dagre, d3-force, ELK layered, tree, radial, concentric and circular-cluster in `utils/layouts.js`, plus a Sigma.js/WebGL renderer with ForceAtlas2 for large graphs. |
| Dark mode / theme engine | **Ships.** CSS-variable theming with light/dark/auto, Gruvbox / Solarized / One Dark / theme.park presets, custom palettes, and Theme Park JSON import/export (`theme/presets.js`, `api/branding.py`). |
| Guided onboarding wizard | **Ships.** Seven-step OOBE (`start`, `domain`, `account`, `theme`, `regional`, `email`, `summary`) gated on `bootstrap_status`. A post-login product tour is absent. |
| API-first / trigger scans from CI | **Mostly ships.** OpenAPI at `/api/openapi.json`, all routes under `/api/v1`, scoped API tokens and service accounts with a published scope catalog (`core/token_scopes.py`). CI can already POST to discovery with a scoped token. What is missing is outbound *generic* webhooks, not inbound API access. |
| Org → Site → VLAN hierarchy | **Partially ships.** `Site` and `Vlan` tables with CRUD, and `Network.site_id`. It is flat — no Region/Building/Rack tree, and nothing else is site-scoped. |
| SLOs / uptime reporting | **Partially ships.** Per-monitor uptime at 24h / 7d / 30d from `telemetry_timeseries` and 365d / total from `monitor_daily_stats`. No user-defined SLO targets, no error budgets, no 60/90-day window, no status page. |
| Config backups / vaulting | **Different feature ships.** Full-state snapshot and `cb restore` exist. Per-device network config backup does not — see §4, I recommend against it. |
| Topology time travel | **Genuinely absent.** Real gap; see §2.4. |
| Traffic-flow pulse animation | **Genuinely absent.** Cosmetic; low priority. |
| External Prometheus/Influx ingest | **Genuinely absent.** Exposition exists at `/api/v1/metrics/metrics`; there is no remote-write receiver and no Influx path. I consider becoming a Prometheus frontend a strategic mistake — see §4. |

The prior draft's priority matrix should be discarded: it rated already-shipped features as
"Critical / Huge" work items.

---

## 2. Genuine gaps that matter, in priority order

### 2.1 Most collected telemetry can never raise an alert

This is the largest asymmetry in the product. Circuit Breaker collects agent host samples,
`hardware_live_metrics`, Proxmox telemetry, disk, CPU, memory and temperature series, retains them
on a hot/warm/cold ladder, and charts them. **The only things that can notify a human are monitor
`down`/`recovered` transitions and certificate-expiry milestones.** There is no threshold, no
duration clause, no hysteresis, no metric predicate of any kind — grep for `AlertRule`,
`alert_rule`, `ThresholdRule`, `notification_rule` returns nothing. `NotificationRoute` has exactly
one routing key, a severity floor.

So the most common homelab alert requests — "the ZFS pool crossed 90%", "the UPS is on battery",
"that drive's SMART reallocated-sector count moved", "CPU has been pegged for ten minutes" — are
unexpressible against data already in the database.

Three dangling wires show the intent existed and was never finished:

- `INTEL_ASSET_DOWN = "intel.asset.down"` is defined in `core/subjects.py:42` and published by
  nothing. The enriched down-event-with-blast-radius payload it describes would be the product's
  best alert.
- `FlapIncident.notified_at` (`db/models.py:2825`) is never written. `run_flap_detection()` computes
  flap incidents that notify no one.
- `MonitorStatus.MAINTENANCE` exists (`services/monitoring/state.py:21`) and `decide()` never
  returns it. Pausing a monitor sets `enabled=false` instead, which stops the check rather than
  suppressing the alert — so a planned maintenance window costs you the uptime history for it.

Alongside the rule engine, the lifecycle pieces an SMB will ask for on day one are absent:
acknowledgement, grouping/correlation, escalation, and real maintenance windows. Dedup (60s Redis
window), per-sink dedup, and delivery retry do exist.

**Recommendation.** A metric rule engine is the single highest-value feature left. Scope it
narrowly: rule = (metric, entity selector, comparison, threshold, `for` duration, severity) →
publish on `alert.>`, which the existing notification path already consumes end to end. Finish the
three dangling wires with it — `intel.asset.down` gives you blast-radius-enriched alerts, which is
a differentiator, not a catch-up feature. Add real maintenance windows as suppression rather than
`enabled=false`.

### 2.2 Pagination on core list endpoints — a forced pre-1.0 deadline

`GET /hardware` takes `tag`, `role` and `q` and no `limit`/`offset` (`api/hardware.py:23-30`). The
same holds for services, storage and networks. `GET /admin/export` loads every table with `.all()`.
The graph endpoint assembles the entire topology in memory per request — it is at least carefully
built (single UNION-ALL CTE for edges via `_preload_edge_maps()`, `bulk_conflict_map()` once per
request, `selectinload`), and it is still unbounded. There is no load or perf suite in `tests/`
(grep `perf|load.test|benchmark|stress`).

The timing is what makes this urgent rather than merely important. Your own release policy is that
after 1.0 a route is a documented surface a scoped token may call, and this repo has an
`endpoint_inventory.json` gate enforcing exactly that. `GET /hardware` returning an unbounded JSON
array cannot grow pagination afterward without breaking every client. **This is the one item on
this list where 1.0 is a hard boundary rather than a preference.**

**Recommendation.** Add opt-in `limit`/`offset` (or cursor) with an unbounded default before 1.0 so
the parameter exists in the frozen contract, then lower the default in a later minor. Pair it with
one load test at the sizing profile you publish in `docs/operations/sizing-profiles.md`, so the
documented ceiling has evidence behind it.

### 2.3 Single-point-of-failure detection — the cheapest real differentiator

You already build the dependency adjacency graph and already walk it downstream. Nothing computes
*fragility*: grep for `spof`, `single.point`, `critical.path` finds specs and docs only, no
implementation.

Articulation points and bridges (Tarjan) over the adjacency `dependency_graph.py` already
constructs is a small, well-defined addition, and it inverts the product's value proposition from
descriptive to prescriptive: instead of "here is what breaks if this dies", you get "these three
devices are single points of failure, ranked by how much they'd take with them — fix this one
first." Composed with the existing blast-radius numbers it becomes a fragility score for the whole
lab.

No homelab tool I am aware of does this. It is the best ratio of distinctiveness to effort on this
list, and it needs no new data collection, no new schema, and no new integration.

### 2.4 Topology change history

Genuinely absent, and correctly identified by the prior draft. There is no revision table for
topology, no history for `HardwareConnection`, and no append-only record of membership change —
grep `TopologyHistory`, `topology_snapshot`, `time_travel` finds nothing. `Topology` carries
`created_at`/`updated_at`; hardware carries `discovered_at`/`last_seen`. "Snapshots" in
`api/topologies.py` means named maps, not points in time.

The value is real for both audiences: *when did this device appear on my network*, and *what
changed in the ten minutes before the outage*.

**Recommendation.** Do not build graph versioning. You already have a hash-chained, tamper-evident
audit log that records entity diffs in `Log.diff`, plus `discovered_at`/`last_seen` on hardware. A
per-entity timeline view and a "changes in window" query over data you already store gets most of
the value for a fraction of the effort. Reserve true point-in-time replay for post-1.0.

### 2.5 CVE: unsound matching, and it rots silently in air-gap

The feature ships but has two defects that make it worse than not having it.

**Matching is lexicographic.** `lookup_cves()` filters `version_start <= version >= version_end` as
string comparison, and its own docstring concedes the approximation
(`services/cve_service.py:43-56`). String ordering is not version ordering: `"1.10" < "1.9"`, so a
range ending at 1.9 wrongly excludes 1.10 and ranges are misjudged throughout. Ingestion also keeps
only the **first** `cpeMatch` per CVE (`:224-241`), discarding the rest of the applicability
statement. Vendor/product matching is case-folded string equality against free-text catalog keys and
service names. The result is false positives and false negatives with no way for a user to tell
which they are looking at.

**It cannot refresh air-gapped.** Sync goes over `PUBLIC_HTTP`, which `core/egress.py:60-62` blocks
when `CB_AIRGAP=true`. There is no offline feed import and no bundled snapshot updater. An air-gapped
install therefore shows a vulnerability panel backed by data that silently ages forever — which
directly contradicts "air-gap is first-class."

Also: CVE state never reaches the topology map (`build_topology_graph` sets `ip_conflict` and no vuln
field; grep `cve|vuln` in `MapPage.jsx` is empty), and there is no triage — no accept-risk, no
false-positive, no track-to-fix. Grep `accept_risk`, `false_positive`, `vuln_status` finds no CVE
workflow.

**Recommendation.** Pick one, explicitly. Either invest — proper version comparison, full CPE
applicability, an offline feed bundle you can import from a USB stick, triage state, and a map badge
— or apply your own INC-era policy and scope the surface down to what the build honestly does. What
it must not do is keep claiming vulnerability coverage it cannot substantiate; that is precisely the
pattern the 22-finding register was written to eliminate.

### 2.6 Containers float free of their host

`docker_discovery.py` creates `Service` rows with no `compute_id` and no `hardware_id`
(`:186-197`), so discovered containers are not children of the machine running them, and the graph
only draws container→network edges. For a homelab audience whose entire lab *is* containers, this is
the difference between a map that explains the lab and a map that lists it.

The fix is small — set the parent during sync, and let the existing `hosts` edge render it. Kubernetes
is absent entirely (grep `kubernetes|k8s|kube` in backend app code finds one comment on a cluster-type
enum); that is defensible for homelab and will matter for SMB later.

### 2.7 Per-object authorization — the actual SMB blocker

RBAC has four fixed roles (`viewer`, `editor`, `admin`, `demo`) and permissions are strings scoped
per *resource type* — `write:hardware`, `read:*` (`core/rbac.py:18-43`, `core/token_scopes.py:9-16`).
There is no per-instance grant: `write:hardware:123` is not expressible. There are no custom roles,
no auditor role, and no delegated admin.

So the first thing an SMB asks for — "the contractor sees only the branch office", "this team
manages only their own services" — cannot be expressed at all. This, not tenancy, is what blocks
team use.

**Recommendation.** `Site` already exists with CRUD and `Network.site_id`. Add `site_id` to hardware
and services, then a site-scoped role. That serves most of the SMB need, is a fraction of the risk
of real tenancy, and is forward-compatible with it. See §3.

### 2.8 Zero lock-in is one-way

`GET /admin/export` produces a full entity JSON snapshot and is wired to a Settings button.
`POST /admin/import` exists on the backend, `adminApi.import` exists in `api/client.jsx:434-435`, and
**no frontend code calls it** — the only match in the whole frontend is the definition itself. Data
goes out through the UI and cannot come back in.

Given that zero lock-in is a stated product principle, and given the register already closed
INC-21 for a page reachable only by typing its URL, this is the same defect class: a complete
backend capability with no way to use it. There is also no NetBox or CMDB sync (grep `netbox`
repo-wide: zero matches) and no CSV inventory import, which is what a homelabber migrating off a
spreadsheet actually needs. Note the JSON export deliberately omits graph layouts, so a round trip
loses the map arrangement.

### 2.9 The audit log cannot leave the building

The hash-chained audit log with advisory-lock serialization, spooling, and admin verify/repair is
genuinely strong work — better than most products this size have. But the only ways out are an
authenticated REST query, an SSE stream, and a client-side CSV download on the Logs page. There is
no syslog forward and no SIEM integration (grep `text/csv`, syslog in backend: nothing).

For SMB, exporting the audit trail is most of the reason to keep one. A syslog/HTTP forwarder is
small work against a subsystem that is already built and already trustworthy.

### 2.10 Mobile and public status

"Is the lab okay?" from a phone is a top-three homelab use case. Today: no service worker (grep
`serviceWorker|workbox`: zero), responsive breakpoints in only three files, a `useIsMobile` hook at
768px that hides map labels, and a three-item mobile dock. There are no mobile-specific views.

A public status page was deliberately removed — `status_pages`, `status_groups` and `status_history`
were dropped in `f61dd2dc9ade`. Worth revisiting for SMB, where it is the most externally visible
feature you can ship, but note it reintroduces an unauthenticated public surface and needs its own
hardening pass rather than a straight revert.

A read-only mobile monitors/status view is high appeal for low effort and does not require either.

### 2.11 Smaller, worth doing

- **Notification breadth.** `_DISPATCH` is a hardcoded four-entry dict. ntfy and Gotify are the
  homelab defaults; PagerDuty/Opsgenie are the SMB defaults; a **generic webhook** provider restores
  the "integrate with anything" escape hatch that left with `webhook_rules`. Each is a function.
  `notification_secrets.py` already assumes unknown providers carry a `webhook_url`, so the secret
  handling is in place and only dispatch is missing.
- **Prometheus scrape ergonomics.** `/api/v1/metrics/metrics` is behind `require_auth` plus
  `_check_metrics_auth`. Correct, but every homelabber runs Prometheus, and there is no documented
  scoped-token scrape recipe. This is mostly a docs gap now that scoped tokens exist.
- **Accessibility.** ~293 `aria-*` occurrences, `prefers-reduced-motion` in four stylesheets, no
  focus-trap library, no a11y lint gate. Incidental rather than systematic. Not a homelab blocker;
  can become a hard procurement blocker for public-sector or education SMB.
- **HA / Kubernetes.** Background jobs are leader-elected through PostgreSQL advisory locks
  (`core/job_lock.py`, `SingleOwnerScheduler`), so multi-replica partly works, but there is no Helm
  chart or k8s manifest (glob `**/helm/**`, `**/*k8s*`: zero files). Defensible for a
  mono-container product; note that k3s homelabs are a real and growing slice of the audience.

---

## 3. On multi-tenancy

You said tenancy is planned, so this deserves a direct answer: **the current half-state is a
liability rather than a head start, and it is the one thing on this list I would act on before 1.0
regardless of when tenancy ships.**

What is actually in the tree:

- `tenant_id` on **16 of ~75** tables, all nullable. `compute_units`, `storage`, `monitor_items`,
  `integrations`, `discovery_profiles`, `credentials`, `topology_nodes` and `topology_edges` are
  among those without it.
- RLS policies on 14 tables in `0040_rls_policies.py`, keyed on
  `current_setting('app.current_tenant')` — but the migration only `ENABLE`s RLS, never `FORCE`s it,
  and separately sets `row_security = off` on the app role. The app role also owns the tables. That
  is **two independent bypasses**, and `main.py:353-408` documents the owner-bypass problem itself.
- `tenant_middleware.py` unconditionally sets the tenant ContextVar to `None`, so the checkout hook
  in `db/session.py:50-69` clears `app.current_tenant` on every connection.
- `api/tenants.py` answers 410 by design, per ADR 0003.
- The handful of app-layer tenant comparisons (`monitor_service.py:290-307`,
  `probe_eligibility.py:183-186`) only fire when *both* sides are non-NULL — so today they no-op.

The trap is concrete: `seed_default_team.py` warns that assigning `tenant_id=1` activates the read
rule. Someone — a future you, or a user reading the migration — will conclude tenancy is a flag away,
set tenant IDs, and get partial isolation over 21% of the schema with RLS bypassed twice, while the
UI looks like it is working. Silent partial isolation is worse than none, because none is honest.

**Recommendations, in order:**

1. **Before 1.0, make the half-state unambiguous.** Either delete the dormant columns and RLS
   migration, or add a startup assertion that refuses to boot if any `tenant_id` is non-NULL while
   the middleware pins the context to `None`. Right now the schema and the product contract disagree,
   and only the ADR resolves it.
2. **Do not let 1.0 foreclose pooled tenancy.** Three decisions in the current API make a later
   pooled model painful and are cheap to hedge now: globally sequential integer IDs everywhere (an
   enumeration surface the moment rows from different customers share a table), a single global
   `AppSettings` row, and authorization that has no per-object dimension (§2.7). Pagination (§2.2)
   is on this list too — a tenant-scoped list endpoint needs it.
3. **Ship Sites + delegated admin instead, and call it that.** For self-hosters, "multi-tenancy"
   almost always means RBAC and scoping, not isolation; only MSPs and hosting need a true boundary.
   Site-scoped roles serve the SMB case, carry a fraction of the risk, and are a strict subset of
   what real tenancy needs later.
4. **When you do build it, treat it as a security program, not a feature.** The audit's estimate is
   right: mandatory tenant at the auth layer, `tenant_id` on all owned tables with backfill and NOT
   NULL, predicates in every route/service/worker/WS path, `FORCE ROW LEVEL SECURITY` under a
   non-owner role, tenant-aware backup/restore/export, and an adversarial cross-tenant test matrix.
   Keeping "separate deployment per trust boundary" as the supported answer for 1.x is the right
   call.

---

## 4. Things I recommend *not* building for 1.0

Saying no explicitly is worth as much as the list above.

- **Network device config backup.** Genuinely absent and genuinely SMB-valuable, and it is a
  different product — per-vendor drivers, credentialed write-adjacent access, diff storage. Oxidized
  and RANCID exist. Integrate later; do not build.
- **Prometheus/Influx ingest ("frontend for Prometheus").** The prior draft called this an instant
  win. It is a strategic trap: it makes you a Grafana competitor on Grafana's turf, doubles the
  telemetry model, and dilutes the thing you are actually best at. Keep exposing metrics outward
  (§2.11) so people can point their existing Prometheus at you — that is the same win with none of
  the cost.
- **Kubernetes pod discovery.** Defer until a real SMB pipeline asks. Docker parentage (§2.6) is
  worth ten times as much per unit of effort for the current audience.
- **Traffic-flow pulse animation.** Cosmetic. Revisit once §2.1 and §2.3 make the map prescriptive;
  it lands much better on top of those.
- **Full topology versioning.** Superseded by the audit-log timeline in §2.4.
- **i18n.** Already correctly scoped out; INC-09 settled it.

---

## 5. Priority

Effort is rough engineering-weeks for one person familiar with the codebase.

| # | Item | Homelab | SMB | Effort | Pre-1.0? |
|---|---|---|---|---|---|
| 2.2 | Pagination on core list endpoints + one load test | Low | High | S | **Yes — API contract freezes** |
| 3.1 | Resolve the dormant tenancy state | Low | High | S | **Yes — correctness** |
| 2.8 | Wire up import; add CSV inventory import | High | Med | S | **Yes — stated principle** |
| 2.6 | Parent containers to their host | High | Med | S | Yes |
| 2.11 | ntfy / Gotify / generic webhook sinks | High | Med | S | Yes |
| 2.1 | Metric alert rule engine + maintenance windows + ack | **Critical** | **Critical** | L | 1.0 or 1.1 |
| 2.3 | SPOF / fragility analysis | High | High | M | 1.0 — best differentiator |
| 2.5 | CVE: fix matching, offline feed, triage — or scope down | Med | High | M–L | Decide before 1.0 |
| 2.7 | Site-scoped roles / per-object authz | Low | **Critical** | M | 1.1 |
| 2.4 | Change timeline over the audit log | High | High | M | 1.1 |
| 2.9 | Audit syslog / SIEM forward | Low | High | S | 1.1 |
| 2.10 | Read-only mobile status view | High | Med | M | 1.1 |
| 2.10 | Public status page (re-scoped, hardened) | Med | High | M | Post-1.0 |
| 2.11 | Accessibility program | Low | Med | L | Post-1.0 |

**If I had to pick three:** the metric rule engine (§2.1) because you already collect the data and
cannot alert on it; SPOF analysis (§2.3) because it is the cheapest genuinely novel thing here; and
pagination (§2.2) because it is the only item whose window closes at 1.0.
