# Intel — fleet vulnerability console

**Status:** design, approved 2026-09-17. Extends
[approved-UI plan 04](approved-ui/04-vulnerability-assessment.md), which named Intel as an
entry point into the assessment workflow and left that link unbuilt. Supersedes nothing.
**Baseline:** `dev` @ `30f8398d`, `VERSION` = `0.4.2`.
**Scope:** what `/intel` shows, the fleet-wide assessment contract behind it, and a home for
the analytics outputs that have none.

---

## 1. What is actually broken

### 1.1 The page does not deliver what the navigation entry sells

`data/navigation.js:179` describes Intel as "Review vulnerability and operational
intelligence", with the aliases `cve`, `vulnerabilities`, `risk` and `security
intelligence` — the navigator's search matches all four to this route.

`pages/IntelPage.jsx` renders capacity forecasts and right-sizing recommendations. There is
no vulnerability content on it of any kind. A user who searches "cve" is sent to a page
about disk-saturation projections.

### 1.2 Vulnerability assessment has no fleet view at all

Plan 04 shipped a truthful per-entity assessment: `AssessmentResult` keeps readiness
(`unavailable` / `unassessed` / `partial` / `completed` / `stale`) separate from findings,
and `VulnerabilityPanel.jsx` renders that separation on hardware, compute and service detail
views.

Every one of those surfaces answers "what about *this* asset". Nothing answers "what about
the fleet". `GET /api/v1/cve/entity/{type}/{id}` is the only assessment route
(`api/cve.py:37`), so "how many assets can't be assessed at all" is a question the product
cannot answer, and the identity-correction work it implies — the single most common blocker,
since an asset with no product/version is permanently unassessed — is a to-do list with no
list.

### 1.3 `FlapIncident` is computed, stored, and read by nothing

`run_flap_detection` (`services/intelligence/analytics.py:212`) runs on every analytics pass,
writes and resolves rows in `flap_incidents`, and no endpoint selects from that table —
`grep -rn FlapIncident apps/backend/src/app` outside the model and the writer returns
nothing. There is no frontend reference either. Detection of flapping hardware has been
running on every install and has never been visible to anyone.

### 1.4 The page predates the shared UI

`IntelPage.jsx` imports nothing from `components/common/`. It is raw
`<table className="entity-table">` with inline `style={{ opacity: 0.7, fontSize: 12 }}`,
a bare `Loading…` string for its loading state, and a `data-warning` attribute on
near-threshold forecast rows that no stylesheet reads — the warning is in the DOM and
invisible. It is the only page in `pages/` at that size with no shared primitives.

## 2. Goals

1. Intel becomes the fleet security surface its navigation entry already promises.
2. The fleet numbers and the entity panel's numbers are the same numbers **by
   construction**, not by careful maintenance.
3. The most common blocker — a missing or wrong product identity — is fixable from the
   console without losing the operator's place.
4. Capacity, right-sizing and flapping get a home, and flapping gets a reader at last.
5. The page is honest in the degraded states that matter most: no feed, stale feed,
   air-gapped install, capped traversal.

## 3. Non-goals

- **No bulk identity correction.** One entity at a time, reusing the shipped
  revision-checked PUT. A bulk write path is a separate decision with its own
  authorization and audit questions.
- **No feed sync trigger from Intel.** `POST /cve/sync` stays where it is, in settings.
- **No persisted assessment history.** Nothing new is stored; see §4.6.
- **No anticipation of the Posture Engine.** `specs/2026-08-23-posture-engine-design.md`
  will own durable findings with a lifecycle, first-seen dates and dispositions. This page
  must be easy to fold into that later, not a half-built version of it.
- **No job-status source.** See §6.3.

## 4. The fleet assessment contract

### 4.1 Why the obvious implementation does not work

`assess_entity` filters candidates with `func.lower(CVEApplicability.product) == ...`
(`services/intelligence/cve_assessment.py:259`). The table's index is on the raw columns
(`Index("ix_cve_applicability_vendor_product", "vendor", "product")`, `db/cve_models.py:77`),
and ingest stores vendor and product **verbatim** out of the CPE string — `parse_cpe`
(`services/intelligence/cve_matching.py:80-89`) does no case folding, so the defensive
`lower()` is correct and the index cannot serve the predicate.

Each assessment is therefore a full scan of `cve_applicability`, which lives in SQLite at
`data/cve.db` (`db/cve_session.py:31`) and holds millions of rows after a full NVD ingest.
The entity panel pays that once per load. A fleet pass that called `assess_entity` in a loop
would pay it **once per entity**; memoizing by identity would still pay it once per
*distinct* identity. Neither is acceptable.

### 4.2 One scan per request

The pass issues **one** candidate query for the whole fleet: `lower(product) IN (...)` over
the distinct products, partitioned per product so `MAX_CANDIDATES` applies **per product**
rather than as a single global `LIMIT`. A global limit would let one noisy product
(`linux_kernel`) consume the entire budget and starve every other identity, and each row's
`candidate_limit` flag would then mean nothing. Candidates are grouped in Python and handed
to the identities that need them.

### 4.3 The refactor that makes parity structural

`assess_entity` splits into three, with its current body preserved:

| Function | Responsibility |
|---|---|
| `resolve_assessment_identity` (exists) | entity → identity, override or inventory |
| `assess_identity(cache_db, identity, feed, assessed_at)` | candidate query for one identity, then evaluate |
| `evaluate_candidates(candidates, identity, feed, assessed_at)` | the matching loop, given candidates |

`assess_entity` becomes `resolve_assessment_identity` → `assess_identity`, unchanged in
behavior. The fleet pass does its batched query and calls `evaluate_candidates` directly.

Both paths run the same evaluation code, so Intel and the entity panel cannot drift. §9.1
locks that with a parity test rather than trusting it.

### 4.4 The pass

New module `services/intelligence/fleet_assessment.py`. `cve_assessment.py` is ~330 lines
and does one job well; the fleet pass is a second job.

1. Bulk-load identity source columns for hardware, compute units and services — three
   queries, mirroring `_entity_values` (`cve_assessment.py:44`) rather than re-deriving it.
2. Bulk-load `EntityAssessmentIdentity` overrides — one query.
3. `get_feed_state` once for the whole pass.
4. Resolve each entity to an identity; group entities by
   `(vendor, product, version, version_scheme)`.
5. One batched candidate query (§4.2); `evaluate_candidates` once per distinct identity;
   fan each result out to its entities.

Assessment covers **three** entity types. Storage has no identity path
(`_entity_values` raises for it) and is out of scope, as it already is for
`cves_for_entity`, which returns an explicit unassessed result for any other type.

### 4.5 Memoization

A bounded LRU keyed on `(feed_generation, vendor, product, version, version_scheme)` holds
each identity's assessment. `feed_generation` is part of the key, so a completed sync
invalidates every entry without an explicit purge, and an identity correction moves to a
different key by definition. This is required, not an optimization: without it every page
load re-pays §4.2's scan.

### 4.6 Session ownership

The `/cve` routes take **no** `Depends(get_db)`. `cve_service.assessment_for_entity` opens
`SessionLocal()` *and* `CVESessionLocal()` itself (`services/cve_service.py:120-123`),
because the cache is a second database with its own engine. The fleet endpoint follows that
local pattern: a `cve_service.fleet_assessment()` façade owns both sessions; the pure pass
underneath takes both explicitly so it is testable.

This is a deliberate exception to CLAUDE.md's `Depends(get_db)` rule, recorded here so it is
not "corrected" back into a broken shape.

### 4.7 `GET /api/v1/cve/fleet`

It belongs to the service that owns the contract, beside `/cve/entity/...`, and the frontend
`cveApi` client already exists. Response:

| Field | Meaning |
|---|---|
| `feed` | the existing `FeedState`, computed once for the pass |
| `assessed_at` | when the pass ran |
| `summary` | entity counts per state, entities with findings, severity histogram over each entity's *worst* finding |
| `rows` | one per entity (below) |
| `limits` | what the pass could not do |

Row: `entity_type`, `entity_id`, `name`, `state`, `reason_code`, `identity`
(vendor/product/version/provenance/revision), `finding_count`, `max_severity`, `max_cvss`,
`completeness`.

**Bounding.** A cap on distinct identities assessed per request, starting at 250. Reaching it
does not truncate silently. Entities beyond the cap return `state: "unassessed"` with a new
`reason_code: "fleet_limit"`, and `limits` says the cap was reached — the same discipline
`candidate_limit` already follows.

`fleet_limit` is a new member of the `AssessmentReason` literal (`schemas/cve.py:11`). The
addition is backward compatible: the per-entity endpoint never emits it, and
`describeAssessment` already falls back safely for an unrecognised reason. It must still be
given a `GUIDANCE_BY_REASON` entry in `lib/vulnerabilityAssessment.js` — a reason code with no
guidance reaches the operator with an explanation and nothing to do about it, which is the
exact defect just fixed for `credential_unavailable` and its siblings in notification
delivery.

**No pagination.** The summary requires the full pass anyway, so paging the response would
save bytes rather than work, and it would let the visible rows disagree with the counts
above them. The table filters and pages client-side over a complete set.

### 4.8 `GET /api/v1/intel/flap-incidents`

`?active=` and `?limit=`, returning `asset_type`, `asset_id`, `asset_name`, `window_start`,
`window_end`, `transition_count`, `is_active`, `resolved_at`. `asset_name` is resolved the
way `ResourceEfficiencyOut` already does it (`api/intel.py`). This is the reader §1.3 has
been missing.

## 5. Page composition

`IntelPage.jsx` becomes a ~110-line shell: read `?tab=`, render `Tabs` with `panelPropsFor`
from `components/common/Tabs.jsx`, delegate to a tab. Unknown or absent `tab` falls back to
`vulnerabilities`. Same deep-link pattern as `SettingsPage` and `IPAMPage`.

```
pages/IntelPage.jsx                    shell, ?tab=vulnerabilities|operations
components/intel/
  FleetAssessmentTab.jsx               summary + filters + table
  FleetSummaryStrip.jsx                readiness tiles
  FleetAssessmentTable.jsx             rows, sort, expansion
  AssessmentStateChip.jsx              state -> chip
  IdentityCorrectionDrawer.jsx         Drawer + revision-checked PUT
  OperationsTab.jsx                    capacity / right-sizing / flapping
hooks/useFleetAssessment.js            fetch, filter state, post-correction refresh
lib/fleetAssessment.js                 pure: filter, sort, severity order
styles/intel.css                       reuses vulnerability.css severity badges
api/client.jsx                         + cveApi.getFleetAssessment
api/intel.js                           + listFlapIncidents
```

Reused rather than rebuilt: `lib/vulnerabilityAssessment.js` already exports
`describeAssessment`, `describeIdentityProvenance`, `ZERO_MATCH_TITLE`, `ZERO_MATCH_CAVEAT`
and `formatAge` — Intel and the entity panel say the same words about the same state because
they read the same table. `Panel`, `StatTile`, `Banner`, `EmptyState`, `Drawer`,
`SkeletonTable` from `components/common/`; paging helpers from `lib/inventoryList.js`.

### 5.1 Readiness leads; there is no score

The summary strip counts **Assessed / Needs identity / Stale / Unavailable** first, then a
severity histogram over each entity's worst finding.

There is deliberately no single score. Plan 04's whole contract is that "no findings" and
"could not assess" are different facts; one aggregate number re-merges them, and a green
number computed off a feed that was never ingested is the exact failure that plan existed to
end.

### 5.2 Row expansion fetches, it does not duplicate

Rows carry counts and worst severity only. Expanding one calls
`GET /cve/entity/{type}/{id}` — the identical call the entity panel makes — and renders the
result with the existing evidence components.

So Intel never grows a second findings renderer, the fleet payload stays small, and an
expanded row is consistent with the entity page by construction. The entity name is also a
plain link to its detail view.

### 5.3 Filters and sort

Client-side over the complete set: state chips, free text over name and product, severity
floor. Default sort is worst severity descending, then finding count, then name, tie-broken
on `(entity_type, entity_id)` so the order is stable across reloads. Filter logic lives in
`lib/fleetAssessment.js` as pure functions, testable without a DOM.

### 5.4 Correction flow

`Correct identity` opens a drawer, PUTs with `revision`, and on success patches the row from
the per-entity response **and** refetches the fleet, so the summary is never locally
recomputed guesswork. On a 409 the drawer keeps entered values and re-reads the identity —
the behavior `VulnerabilityPanel` already ships, including the fix that stopped a first
correction conflicting with itself.

## 6. Operations tab

Three `Panel`s over the analytics outputs.

### 6.1 Capacity forecasts

The existing `GET /intel/capacity-forecasts`, re-rendered with shared primitives. Rows within
`warning_threshold_days` of projection are **visibly** distinguished — today that state is a
`data-warning` attribute nothing styles (§1.4).

### 6.2 Right-sizing and flapping

Right-sizing keeps its existing endpoint. Flapping consumes §4.8 and shows the asset, the
window, and the transition count.

### 6.3 What the empty states may claim

The current empty text says the job may not have run yet *or* there may be nothing to
report. That wording is honest precisely because no job-status source exists:
`startup/jobs.py` registers scheduled jobs and nothing reads their state back.

Making it precise means the analytics worker recording a last-run timestamp — new stored
state with its own decision. Out of scope; the two-possibility wording is kept, and each
panel additionally reports the newest `evaluated_at` among the rows it did receive.

## 7. Honesty, errors, permissions

- **Feed unavailable** → one `Banner` at the top and every row `unavailable`, not two hundred
  identical warnings.
- **Completed with zero matches** → `ZERO_MATCH_TITLE` with `ZERO_MATCH_CAVEAT`. Never
  "safe", never a green tile.
- **`limits` is rendered**, never swallowed. A capped pass makes the summary a floor rather
  than a total, and the page says so where the counts are.
- **Loading** is `SkeletonTable`, not a bare string. **Errors** render a `Banner` with Retry
  that leaves the tabs usable.
- **Air gap is a first-class state.** `CB_AIRGAP=true` means the NVD feed never ingests, so
  the console runs permanently in `feed_missing`. It must stay useful there — readiness,
  identities and the Operations tab are all fully functional without a feed — and must never
  render an un-ingested feed as an all-clear. §9.1 tests this.
- **Permissions.** The `/cve` router mounts with `require_auth` (`api/routing.py:413-417`), so a
  viewer reads the console; `Correct identity` is hidden without write via `useAuth`, the
  same split `VulnerabilityPanel` uses, and the PUT keeps `require_write_auth`. No permission
  is widened anywhere.
- **No scoping to apply.** RBAC is role- and scope-based with `read *` for viewers
  (`core/rbac.py:26`); inventory has no per-row or per-site filtering and Hardware carries no
  soft-delete column. The pass reads all rows, and that is correct rather than an oversight.
- **Navigation is unchanged.** `data/navigation.js:179` already promises this page. It starts
  being true.

## 8. Performance budget

- **One** `cve_applicability` scan per uncached fleet request, independent of entity count
  (§4.2).
- `evaluate_candidates` runs once per **distinct** identity, not per entity — the fleet's
  cost tracks identity diversity, and a rack of identical Debian hosts costs one evaluation.
- A warm memo (§4.5) serves repeat loads without touching the cache database.
- Query counts are asserted in tests, following the precedent set by plan 07's locked
  query-count budgets. A regression that reintroduces per-entity querying fails a test rather
  than a user's page load.

## 9. Testing

### 9.1 Backend

`tests/services/test_fleet_assessment.py` (beside the existing `test_cve_assessment.py`):

- **Parity** — for every entity, the fleet row's state and reason equal `assess_entity`'s for
  that entity. This is what keeps §4.3's split honest permanently.

  **Scope, established while planning:** the per-entity query applies its vendor filter in SQL
  before its `LIMIT`, while the batched query caps per `(vendor, product)` pair. For any pair
  under the cap both select the same candidates and parity is exact. For a pair *at* the cap
  both paths report `candidate_limit` and neither claims completeness, but their candidate sets
  may differ. The parity test therefore asserts exact equality for uncapped identities and
  equality of the `candidate_limit` signal for capped ones. Asserting identical findings for a
  capped pair would be asserting something untrue.
- **Batching** — N entities over M distinct identities issue **one** candidate query and call
  `evaluate_candidates` exactly M times, asserted with a spy and a query counter.
- **Per-product cap** — a product with more than `MAX_CANDIDATES` candidates does not starve
  other identities, and only its own rows carry `candidate_limit`.
- **Identity cap** — reaching the 250-identity cap marks the remainder and populates
  `limits`; it never silently drops entities.
- **Feed states** — unavailable short-circuits the pass; stale keeps findings and labels them.
- **Air gap** — with no ingested generation, the pass returns `feed_missing` for every row and
  no state that could read as an all-clear.
- **Summary reconciliation** — counts equal what the rows say, per state and per severity.

`tests/api/test_cve_fleet.py` and `tests/api/test_intel_flap_incidents.py` cover shape,
auth, and viewer access. Both new routes are added to
`apps/backend/src/app/security/endpoint_inventory.json` —
`test_full_endpoint_inventory_matches_runtime_routes` fails otherwise, as it did for
`/admin/diagnostics`.

### 9.2 Frontend

- `__tests__/fleet-assessment-lib.test.js` — pure filter, sort, severity ordering, summary
  derivation.
- `__tests__/intel-page.test.jsx` — **rewritten**. It currently renders the old page and
  asserts on `forecast-row-*` / `efficiency-row-*` testids; those assertions move to the
  Operations tab test. It becomes the shell test: tabs, `?tab=` deep link, unknown tab
  fallback.
- `__tests__/intel-api.test.js` — **extended** for the new client functions.
- `__tests__/fleet-assessment-tab.test.jsx` — each assessment state, empty, viewer versus
  editor, correction success and 409, `limits` rendered.
- `__tests__/intel-operations-tab.test.jsx` — the three panels, including flapping.

### 9.3 End to end

`apps/frontend/e2e/accessibility.spec.ts` gains `/intel` on both tabs. The tablist is new
ARIA and that spec is its gate.

### 9.4 Gates

`make lint`, then **`make verify-full`** — this touches `apps/backend/src/app`, which
`make verify` skips entirely. The coverage ratchet is not lowered.

## 10. Compatibility and follow-up

**No migration.** Nothing new is persisted: the pass is computed, the memo is in-process, and
`flap_incidents` already exists. `GET /cve/entity/{type}/{id}` keeps its current shape and its
`items` compatibility alias, so the entity panel is untouched by the refactor.

**Follow-up, deliberately not in this design.** Store normalized lowercase vendor and product
at ingest so `ix_cve_applicability_vendor_product` can serve the predicate, and drop the
`lower()` from the query. That turns §4.1's scan into an index seek and speeds up the
existing entity panel too. It is a `cve.db` schema change — the file is a rebuildable cache,
but shipped installs need a resync or a backfill, so it deserves its own decision rather than
being smuggled in here.

## 11. Documentation

`docs/business_intelligence.md` documents both the Intel page ("Where these appear") and the
`/intel` endpoints. It gains `GET /cve/fleet`, `GET /intel/flap-incidents`, and a corrected
description of what the page shows. Flap detection is currently documented as an analytics
job with no consumer; that becomes a described surface.

## 12. Delivery slices

Two slices, in order. Each is independently shippable and independently testable.

**Slice A — the fleet contract and the Vulnerabilities tab.** §4 in full (the three-way
refactor, the batched query, the memo, `GET /cve/fleet`), §5, and the §7 honesty rules. This
is the slice that makes the navigation entry true. The Operations content stays exactly where
it is meanwhile, rendered by the current code, so nothing regresses while A is in flight.

**Slice B — the Operations tab.** §4.8's flap endpoint and §6. Smaller, and it depends on A
only for the tab shell.

Within each slice: contract tests first, then the UI against fixtures, then the service, then
real data end to end. A mocked surface may be reviewed in tests but is never presented as a
working capability — the standing rule from the approved-UI plans.

## 13. Acceptance

- [ ] `/intel` opens on a fleet assessment whose counts match the entity panels behind them.
- [ ] An entity reading **Needs identity** can be corrected from the console and re-assesses
      immediately, without losing filter or scroll position.
- [ ] A fleet request issues one candidate query regardless of entity count, asserted by test.
- [ ] Every degraded state — no feed, stale feed, air-gapped, capped — renders as itself and
      never as an all-clear.
- [ ] Flapping hardware is visible to an operator for the first time.
- [ ] `make lint` and `make verify-full` pass; coverage ratchet unchanged.
- [ ] `docs/business_intelligence.md` describes both new endpoints and the new page.
