# Missing UIs — Design (INC-10 … INC-14)

**Date:** 2026-08-24
**Branch:** `dev`
**Source finding register:** `docs/1.0.0-incomplete-features.md`
**Covers:** INC-10, INC-11, INC-12, INC-13, INC-14
**Status:** Approved design; implementation slices in [`10-missing-uis-implementation.md`](./10-missing-uis-implementation.md).

---

## 1. Purpose and scope

The register catalogues five findings whose common shape is *implemented backend
capability with no way to use it*. This design specifies the user surfaces that close
them, plus the backend changes those surfaces cannot honestly ship without.

| ID | Finding | Surface |
|---|---|---|
| INC-10 | Business Intelligence has no UI | `/intel` page + blast-radius panel on entity detail views |
| INC-11 | Knowledge Base has no UI and no docs | Settings → Knowledge Base tab |
| INC-12 | Audit-chain verify/repair has no UI | `/logs/audit` view + chain-integrity panel |
| INC-13 | Agent server-key rotation has no UI | Rotation panel on Agents page |
| INC-14 | Scoped service accounts API-only; token admin incomplete | Settings → Security → Access Tokens |

**Not in scope.** INC-04/05 (their own P0 fixes; INC-04 intersects this design and is
addressed in §7), INC-07, INC-08, INC-09, INC-15, INC-16, INC-18, INC-19, INC-20.
Converting `require_role`-guarded routes to per-resource `require_scope` is explicitly
out of scope — see §11.

---

## 2. Decisions taken

Recorded so the plan does not relitigate them.

| # | Decision | Rationale |
|---|---|---|
| D1 | All five findings in one design | They share one pattern applied five times |
| D2 | Each surface homed to its own subsystem, not a new admin console | Adds one dock entry rather than five; `DEFAULT_ORDER` already carries 16 |
| D3 | BI = page for forecasts/efficiency, inline panel for blast radius | Different interaction shapes; blast radius is a per-asset question |
| D4 | Audit view + verify + repair behind a guarded dialog | The awkward API contract becomes the dialog's validation |
| D5 | INC-14 includes its backend deltas | A scope picker over today's backend would be a lying control |
| D6 | Rotation shows fleet adoption, incl. per-agent state | The columns exist for exactly this (`models.py:432-450`) |
| D7 | KB is curation-framed CRUD; no import endpoint | YAGNI; export already exists, import is a separate ask |
| D8 | BI visible to all authenticated users | Matches what `/intel` already serves; no UI/API divergence |
| D9 | B1 (`require_role` honours token scopes) lands with back-compat defaults | Closes the escalation without a flag day |

---

## 3. Architecture

### 3.1 Placement

`RequireAdmin` / `RequireEditor` already exist as route guards in `App.jsx`.
`SettingsPage.jsx:1761` sets the pattern to follow: `{activeTab === 'users' && isAdmin &&
<AdminUsersPage embedded />}` — a full page component embedded via one line.

**Every new surface is its own file. Host files gain a registration line, not a feature.**
This is a hard constraint: `SettingsPage.jsx` is 1876 lines, `LogsPage.jsx` 1437,
`ProfileModal.jsx` 1130. Closing five findings must not make them worse.

| Finding | Component | Home | Guard |
|---|---|---|---|
| INC-11 | `pages/KnowledgeBasePage.jsx` | `SETTINGS_TABS` entry `kb`, `adminOnly` | route is `require_role("admin")` |
| INC-12 | `components/logs/AuditChainPanel.jsx` + `LogsPage` `auditMode` | route `/logs/audit` | `<RequireAdmin>` |
| INC-13 | `components/agents/ServerKeyRotationPanel.jsx` | `AgentsPage` | admin-only render |
| INC-14 | `components/settings/AccessTokensManager.jsx` | Settings → Security tab | admin |
| INC-10 | `pages/IntelPage.jsx`, `components/details/BlastRadiusPanel.jsx` | route `/intel`; four detail views | none |

**Navigation delta.** `/intel` enters `NAV_MAP` and `DEFAULT_ORDER` (one new dock icon).
`/logs/audit` enters `NAV_ITEMS` under Administration but **not** the dock — it is a
sub-view of Logs, not a peer of Map.

KB goes to Settings rather than DiscoveryPage because discovery configuration already
lives there (`connectivity` tab, "Auto-discovery and API settings"). A cross-link from
Discovery covers discoverability.

### 3.2 The one new shared primitive

`components/common/HighRiskConfirmDialog.jsx`.

Props: `open`, `title`, `body`, `confirmPhrase`, `reason` (`{required, minLength}` or
absent), `confirmLabel`, `onConfirm({reason})`, `onCancel`, `busy`, `error`.
Confirm stays disabled until the typed phrase matches `confirmPhrase` exactly and any
reason constraint is satisfied. Server errors render via `error` — client validation
makes the 4xx unreachable in normal use, it does not assume it away.

The phrase is always *the thing you would get wrong*:

| Action | Phrase | Reason |
|---|---|---|
| Audit chain repair | `REPAIR_AUDIT_CHAIN` | required, ≥12 chars |
| Server-key rotation | `ROTATE` | — |
| Token revoke / rotate | the token's own label | — |

For repair this is **not invented**: `REPAIR_AUTHORIZATION` (`core/audit_chain.py:19`)
and `Field(..., min_length=12)` (`api/admin_audit.py`) are the server's contract, so the
dialog enforces the contract rather than restating it.

The existing `ConfirmDialog` continues to serve ordinary deletes (KB rows).

### 3.3 API modules

New per-domain modules, following the existing `api/agents.js` / `api/monitor.js`
convention rather than pushing `api/client.jsx` (589 lines, 30 exports) further:

- `api/kb.js` — list / create / update / delete / export, for `oui` and `hostname`
- `api/intel.js` — `blastRadius(type, id)`, `capacityForecasts()`, `resourceEfficiency()`
- `api/audit.js` — `verifyChain()`, `repairChain({authorization, reason})`
- `api/tokens.js` — list, create, createServiceAccount, rotate, revoke, `scopes()`
- `api/agents.js` (existing) — gains `serverKeyStatus()`, `rotateServerKey()`

---

## 4. INC-11 — Knowledge Base

`pages/KnowledgeBasePage.jsx`, accepting an `embedded` prop as `AdminUsersPage` does.
Two internal tabs: **MAC OUI Prefixes**, **Hostname Patterns**.

Each tab is an `EntityTable` over the existing list routes, which already order
`seen_count desc` server-side. Columns are the curation story: `seen_count` and
`last_seen_at` are what tell an operator an entry is worth trusting; `source` renders as
a `learned` / `manual` badge. The source filter passes the existing `source` query param.

**Editability is dictated by the API.**

| Table | Editable | Not editable | Why |
|---|---|---|---|
| `kb_oui` | `vendor`, `device_type`, `os_family` | `prefix`, `source`, counters | `PUT /kb/oui/{prefix}` accepts only those three |
| `kb_hostname` | `vendor`, `device_type`, `os_family` inline; `match_type` via row modal | `pattern`, `source`, counters | `PUT` accepts the four; `match_type` is an enum and `EditableCell` is a bare text input |

`prefix` and `pattern` are identity — the API offers no rename, so the UI must not appear
to offer one. `match_type` as a free-text cell would let an operator write a value the
matcher silently ignores.

**Pagination.** `EntityTable` paginates client-side over whatever `data` it receives;
the KB routes paginate server-side at `limit ≤ 500`. Wiring them naively caps the table
at 500 rows while looking complete. Fetch server-side with explicit `offset`/`limit` and
a "Load more"; size `EntityTable`'s page size to the fetch so it does not double-paginate.

Delete uses `ConfirmDialog`. Export downloads from the existing `/kb/{oui,hostname}/export`
routes. No new endpoints.

---

## 5. INC-12 — Audit view and chain integrity

### 5.1 Disposition of `GET /logs/audit`

The register lists this endpoint as an uncalled gap. That is half wrong and the design
does not build to it. `GET /logs` (`api/logs.py:120`) already accepts `category`, is
admin-only, and its parameter list is a strict **superset** of `/logs/audit`'s — the
latter adds nothing and drops `entity_type`, `entity_id`, `entity_name`, `level`,
`severity`, and `search`.

`/logs/audit` is therefore **redundant, not missing** — the same class as the
`GET/PUT /hardware/{id}/ports` row the register itself annotates that way. It gets a
disposition (delete, or keep and document as an API convenience), not an invented caller.

### 5.2 The view

`LogsPage` already owns `LogRow`, `LogsVirtualTable`, `DiffTable`, `ExpandedContent`,
actor avatars, IP-redaction reveal, and URL-synced filters — roughly 850 lines of exactly
what an audit view needs. Rebuilding that would be the most wasteful thing in this design.

Route `/logs/audit` renders `LogsPage` in `auditMode`: `category` pinned to `audit`,
inapplicable filters hidden, title and empty state reworded, `AuditChainPanel` mounted
above the table. Roughly 30 lines in `LogsPage` plus one new component file.

**Trade-off, recorded deliberately.** `auditMode` grows a file already at 1437 lines. The
alternative — extracting the row/table components into `components/logs/` for a standalone
`AuditPage` — is better structure but a large diff across the app's most-used admin page
for no user-visible gain. The mode flag ships now; extraction becomes worthwhile if the
audit view later diverges enough to need it.

### 5.3 `AuditChainPanel`

Calls `GET /admin/audit-log/verify-chain` on mount.

- **Intact:** one quiet line — `chain intact`, `checked_count` verified, time of check,
  and Re-verify.
- **Broken:** escalated — names `first_failure_id`, states plainly that a break means
  entries were altered or removed after being written and that repair relinks the chain
  and appends a repair record but **does not recover the original entries**, and offers
  **Repair chain…** through `HighRiskConfirmDialog`.

Repair itself writes an audit entry, so the panel refetches both verify and the log list
afterward. The repair appearing in the list you are looking at is the confirmation.

---

## 6. INC-13 — Agent server-key rotation

### 6.1 Panel

`components/agents/ServerKeyRotationPanel.jsx`, admin-only, on `AgentsPage`.

**Idle:** current fingerprint, in-use-since, fleet size, `no rotation in progress`, and
**Rotate key…**.

**Active:** both fingerprints, `started_at`, countdown to `overlap_expires_at`, the
adoption rollup, and Rotate disabled with its reason stated — the endpoint 409s while an
overlap runs, so the button must not offer an action the server will refuse. If a POST
races and 409s anyway, refetch status and render the active state rather than an error
toast.

Rotate goes through `HighRiskConfirmDialog` (phrase `ROTATE`). The body states what the
endpoint docstrings say: a fresh successor keypair, a 7-day overlap, pushed immediately
to every connected agent, and that an agent offline for the entire window will fail to
authenticate afterward.

### 6.2 Backend delta

`ServerKeyRotationStatus` (`schemas/agents.py:273`) gains adoption counts derived from
`Agent.server_pk_current_pinned_at` / `server_pk_successor_pinned_at` compared against the
rotation start: total, authenticated-with-successor, still-on-current,
not-seen-since-rotation. Populated only while `active` is true.

**It must be one aggregate query.** `agents.py:284`'s `_latest_samples` exists precisely
because query count must not scale with fleet size, and its docstring notes a test pins
that count. This follows that precedent rather than looping the fleet.

### 6.3 Wording is a constraint, not polish

`models.py:432-450` is explicit that the server sees only which key an agent's
*handshakes have used*, never whether the agent holds the successor. Therefore:

- "authenticated with successor key" — never "has the successor key"
- "not seen since rotation" — never anything predicting failure

During an overlap, `AgentsPage`'s table gains a key-state column carrying the same three
values. Outside an overlap the column is absent.

---

## 7. INC-14 — Access tokens and service accounts

### 7.1 The blocker this closes

Tracing both token paths:

1. **Static UI token** — `core/security.py:523` sets `uid = api_token_row.created_by`, so
   `require_role("admin")` resolves the creating admin and passes.
2. **Service-account JWT** — `uid = 0`, and `core/rbac.py:141` returns `_service_user()`
   with `is_superuser=True` **before any scope check runs**.
3. `require_scope` is used on exactly **two** distinct checks in the entire backend:
   `read:*` and `write:telemetry`. Everything else is `require_role`.

Net: every token, whatever its scopes, is a superuser on every `require_role` route —
settings, users, backups, vault, audit-chain repair. Scopes narrow only that two-check
subset.

INC-04 records the 403 half ("authorized for nothing"). This is the other half, and it
fails in the dangerous direction. **A scope picker shipped over this backend would label a
token "read-only" while it can delete every user in the system** — a worse lying control
than anything currently in the register. Hence D5.

### 7.2 Backend deltas

In dependency order. B1 is a prerequisite for any of the UI.

| # | Change | Notes |
|---|---|---|
| B1 | `require_role` honours token scopes when present. For each required role, check the corresponding scope from the existing `ROLE_DEFAULT_SCOPES` vocabulary — `admin` → `admin:*`, `editor` → `write:*`, `viewer` → `read:*` — and 403 if unsatisfied. Must cover the `uid == 0` early return at `rbac.py:141`, which today returns a superuser before any scope check. | Back-compat: a stored `scopes == []` means **"unscoped — inherit the creator"**, not "no scopes granted". Implemented in `_normalise_token_scopes` (`core/security.py:82-88`), which currently returns `()` for an empty list and must return `None`. That function feeds both `require_scope` and (after B1) `require_role`, so the one change makes deployed tokens keep working *and* closes INC-04's 403 for existing rows. |
| B2 | Validate `scopes` against the catalog on create; 422 on unknown. Reject an empty list. | `CreateServiceAccountRequest.scopes` is today an unvalidated `list[str]`; `read:hardwrae` mints INC-04 through the endpoint that "works". Rejecting `[]` at create prevents re-creating B1's legacy ambiguity. |
| B3 | Shared scope catalog + `GET /auth/scopes` (label + description per scope) | One server-side source so the picker cannot drift from enforcement — the INC-03 lesson |
| B4 | `POST /auth/api-token` accepts `scopes`, defaulting to the creator's effective scopes | **This is INC-04's fix.** B1's reinterpretation of `[]` closes the 403 for existing rows; B4 closes it for new ones. |
| B5 | `APITokenItem` gains `scopes`, `created_by`, creator display name, `is_service_account` | Service accounts are identified today only by the label prefix `"[Service Account] "` (`api/auth.py:478`) — a string convention the UI would otherwise have to parse |
| B6 | Drop the `created_by == current_user.id` filter for admins on **list and delete** | The register cites only the list; `api/auth.py:576-582` has the same filter, so an admin cannot revoke a peer's token even knowing its ID |
| B7 | `POST /auth/api-tokens/{id}/rotate` — mint a replacement with the same label/scopes/expiry, return the secret once, revoke the old | SRV-06's "rotation"; none exists today |

### 7.3 UI

`components/settings/AccessTokensManager.jsx` in the Security tab.

**Inventory table:** label, type (`user token` / `service account`), scopes as chips,
created by, expires (with expiring-soon and expired states), last used, and per-row
Rotate / Revoke. A scope filter toggles All tokens / Mine only.

A legacy token with no stored scopes renders an `inherits creator` chip — B1's
compatibility rule made visible rather than hidden.

**Create:** label, expiry, and an access-level picker fed by `GET /auth/scopes`:

- Read-only — `read:*`
- Telemetry ingest — `read:*` + `write:telemetry`
- Full access — `admin:*`
- Advanced — individual scope selection

**One-time secret:** revealed once with a copy button and an explicit acknowledge before
it can be dismissed. It must never re-render from state after dismissal.

Rotate and Revoke use `HighRiskConfirmDialog` with the token's own label as the phrase —
which is what prevents revoking the adjacent row.

**`ProfileModal`:** its `apiTokens` tab remains as a personal view of your own tokens, but
the create form moves to `AccessTokensManager` — one create path instead of two that
disagree. This also lifts roughly 180 lines out of a 1130-line file.

### 7.4 Preset honesty

The presets name what B1 actually enforces — admin / editor / read-only — rather than a
per-resource matrix. Only `read:*` and `write:telemetry` are checked by `require_scope`
anywhere in the backend today, so a granular matrix would invent distinctions nothing
honours. **Advanced** exists for API-forward use. A per-resource picker becomes worth
building when more routes adopt `require_scope`, not before.

---

## 8. INC-10 — Business Intelligence

### 8.1 `/intel` page

`pages/IntelPage.jsx`, one new dock entry, no role guard — matching what the routes
already serve (D8).

**Capacity forecasts** — already ordered `projected_full_at asc nulls last` server-side.
Columns: host, metric, current value, trend/day, projected full, threshold. Rows whose
projection falls inside `warning_threshold_days` are marked.

**Right-sizing** — grouped by `classification`, with `recommendation` as the payload.
Columns: asset, class, CPU avg/peak, memory avg, recommendation.

### 8.2 Backend deltas

**B8 — names in the response.** `CapacityForecastOut` returns `hardware_id`;
`ResourceEfficiencyOut` returns `asset_type` + `asset_id`. Neither returns a name. A table
of bare integers is unusable, and joining client-side means extra fetches across four
asset types. The name belongs in the response.

**B9 — empty-state distinguishability.** Both tables are filled by `analytics_job`. Before
its first run they are empty, so "no data" must distinguish *the job has not run yet* from
*nothing to report* — otherwise the screen's most common first impression is
indistinguishable from a broken one. The page names the job and its schedule; surfacing a
last-evaluated timestamp is the minimum needed to tell the two apart.

### 8.3 Blast radius

`components/details/BlastRadiusPanel.jsx`, mounted in `HardwareDetail`, `ComputeDetail`,
`ServiceDetail`, and `StorageDetail` — exactly `intel.py`'s `_VALID_TYPES`. Follows the
existing precedent of `VulnerabilityPanel.jsx` (228 lines) and `HardwareThreatProfile.jsx`
(176 lines): self-contained analysis panels mounted into detail views.

Collapsed by default; **fetches on expand, not on detail mount**, since it walks the
dependency graph. `summary` and `total_impact_count` are the headline; the four impacted
lists are grouped by type with each name linking to its own detail route.

**Zero impact renders as an answer, not an empty state.** "Nothing depends on this" is the
most valuable thing the endpoint can say before someone takes a host down.

---

## 9. Error handling

Uniform across all five surfaces.

| Condition | Behaviour |
|---|---|
| 403 | Nav gating and backend disagree — surface as an error, never a blank table |
| 409 (rotate) | Refetch status, render the active state, no error toast |
| 422 (repair, scope validation) | Inline on the offending field, not a toast |
| Network / 5xx | Explicit error state with a retry affordance |

**No fetch failure may render as an empty table.** "Looks fine, does nothing" is this
register's entire subject matter; reproducing it in the screens built to close it would be
a poor outcome.

---

## 10. Testing and documentation

### 10.1 Tests

Following existing conventions in `apps/frontend/src/__tests__/` and the backend suite.

- KB's editable column set matches what `PUT` accepts — the two drifting apart is INC-17
  in miniature.
- `GET /auth/scopes` and the picker's options name the same set, asserted the way
  `tests/api/test_notification_routes_api.py` pins the `Literal` against `ROUTE_SEVERITIES`.
- B1: a scoped token is refused on a `require_role` route it lacks scope for, **and** a
  legacy `scopes == []` token still passes as its creator.
- B2: an unknown scope is a 422; an empty scope list is a 422.
- B7: a rotated token's predecessor no longer authenticates.
- Rotation adoption counts stay one query, pinned by count as `_latest_samples` already is.
- `AuditChainPanel` renders the broken state from a `valid: false` response and refetches
  after repair.
- `BlastRadiusPanel` with zero impact renders as an answer, not an empty state.
- Each surface: renders, respects its role gate, and does not render an error as empty.

### 10.2 Documentation

INC-11 names the docs gap as part of the finding, so docs are a deliverable, not a
follow-up.

- New `docs/knowledge-base.md`, cross-referenced from `docs/discovery.md`
- `docs/audit-log.md:48` corrected — the view it describes now exists
- `docs/business_intelligence.md:5-6` updated; *"no screen in the app calls them"* ceases
  to be true
- New agent server-key rotation runbook
- New tokens / service-accounts page covering scope semantics under B1
- All added to `mkdocs.yml` nav

### 10.3 Register updates

`docs/1.0.0-incomplete-features.md`: INC-10 … INC-14 receive resolution notes in the style
established by INC-01/02/03/06/17, plus a disposition line for `GET /logs/audit` as
redundant (§5.1).

**Filed elsewhere:** the `require_role`-ignores-token-scopes finding (§7.1) is new, is a
privilege-escalation issue rather than an incomplete feature, and belongs in
`docs/1.0.0-release-readiness-audit.md` (security/process). Cross-reference it from INC-04
but file it there.

---

## 11. Explicitly out of scope

- **Converting `require_role` routes to per-resource `require_scope`.** B1 makes role
  gates scope-aware; a per-resource RBAC model is separate work and doing it here would
  quietly widen five screens into an RBAC overhaul.
- **Gating the analytics jobs off** — INC-10's alternative disposition. The screen ships
  instead (D3).
- **A KB import endpoint** (D7).
- **Extracting LogsPage's row/table components** (§5.2) — revisit if the audit view
  diverges.

## 12. Known risks

| Risk | Mitigation |
|---|---|
| B1 changes authorization behaviour for deployed tokens | Back-compat rule in §7.2; explicit tests for the legacy path; release-note treatment |
| `auditMode` grows an already-large `LogsPage` | Panel is a separate file; extraction path recorded in §5.2 |
| KB pagination mismatch silently caps at 500 rows | Server-driven paging specified in §4 |
| Static-token auth scans and HMAC-verifies every `APIToken` row per request (`security.py:513-520`) | Pre-existing and O(tokens); a fleet-wide inventory encourages more tokens. Not fixed here — flagged for the security audit |
