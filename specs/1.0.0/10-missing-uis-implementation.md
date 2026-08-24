# Missing UIs — Sprint Implementation Slices

**Companion spec:** [10-missing-uis.md](./10-missing-uis.md)
**Status:** All five slices planned in full and ready to execute

## Standalone slice plans

- [UI-1 — Knowledge Base](./slices/ui-1-knowledge-base.md)
- [UI-2 — Agent server-key rotation](./slices/ui-2-server-key-rotation.md)
- [UI-3 — Audit view and chain integrity](./slices/ui-3-audit-view.md)
- [UI-4 — Business Intelligence](./slices/ui-4-business-intelligence.md)
- [UI-5 — Access tokens and service accounts](./slices/ui-5-access-tokens.md)

## Deviations from the spec, recorded during planning

Each was found by reading the code the slice touches. All are argued in the
slice that makes them and repeated in that slice's register note.

| Slice | Spec said | Plan does | Why |
|---|---|---|---|
| UI-2 | Per-agent key-state column on the fleet table (§6.3) | Drill-down inside the rotation panel | `FleetTable.jsx:18-21` declares its column list a contract with `FleetRow`'s hand-counted `colSpan` values; a *conditional* 12th column would make them dynamic in the densest table in the app |
| UI-3 | auditMode hides inapplicable filters (§5.2) | Hides nothing | Every filter applies to audit entries; hiding any would remove working functionality |
| UI-3 | — | Also retitles `/logs` to "Logs" | `LogsPage` already titled itself "Audit Log" while sending no `category`; two pages cannot share the title |
| UI-4 | Empty-state distinguishability as a backend delta (§8.2 B9) | Delivered as copy | The job writes nothing when it finds nothing, so `max(evaluated_at)` is NULL in both cases; precision needs job-run tracking, which is scheduler observability |
| UI-5 | `[]` means "inherit the creator" (§7.2 B1) | Static tokens only, never service-account JWTs | A service account's "creator" is the synthetic superuser; inheriting there would promote an empty-scoped token to superuser |
| UI-5 | Full access preset (§7.3) | `*:*`, not `admin:*` | `has_scope` never treats admin as implying read, so `admin:*` alone passes role gates and 403s on every read route |

Slices are numbered by implementation order, not by finding ID — deliberately, since a
slice named `inc-1-…` would collide with finding INC-01 (racks removal, already closed).
The finding each slice closes is named in its **Supports** line and in the table below.

## Sequencing

Cheapest first, deferring the authorization change until the pattern is established.
UI-5 carries the only change that alters behaviour for existing deployments.

| Slice | Closes | Backend change | Why here |
|---|---|---|---|
| UI-1 | INC-11 | none (two contract-pin tests only) | Lowest risk; establishes the settings-tab, API-module, and descriptor patterns the later slices reuse |
| UI-2 | INC-13 | adoption counts on `ServerKeyRotationStatus` | Small and self-contained; builds `HighRiskConfirmDialog` against its first consumer |
| UI-3 | INC-12 | none; disposition for the redundant `GET /logs/audit` | Reuses `LogsPage` machinery and `HighRiskConfirmDialog` from UI-2 |
| UI-4 | INC-10 | names in intel responses; job-run distinguishability | Two ranked tables plus a panel in four detail views |
| UI-5 | INC-14 | B1–B7, including `require_role` honouring token scopes | Largest, and the only slice that changes authorization for tokens in deployed installs |

## Slice UI-1 — Knowledge Base

**Supports:** INC-11
**Depends on:** nothing

- [ ] MAC prefix normalisation helpers, so a pasted `B8:27:EB` is not a 422.
- [ ] `api/kb.js`, keyed by `prefix` for OUI and by `id` for hostname.
- [ ] Tab descriptors, with the inline-editable set contract-pinned from both the
      frontend and the backend so it cannot drift from what `PUT` accepts.
- [ ] `KbTable` with server-driven paging, an honest text filter, and an error state
      that is never an empty table.
- [ ] `KnowledgeBasePage` registered as an `adminOnly` Settings tab via one render line.
- [ ] `docs/knowledge-base.md`, cross-referenced from `docs/discovery.md` and added to
      the MkDocs nav; INC-11 marked Resolved in the register.

**Verification:** Full frontend suite and `pytest apps/backend/tests/api/test_kb.py` pass;
an admin can add, correct, and remove entries in both tables, and a non-admin cannot see
the tab.

## Slice UI-2 — Agent server-key rotation

**Supports:** INC-13
**Depends on:** nothing (introduces `HighRiskConfirmDialog`)

- [ ] `HighRiskConfirmDialog` — type-to-confirm phrase plus optional reason, busy and
      error states.
- [ ] Extend `ServerKeyRotationStatus` with fleet adoption counts derived from
      `server_pk_current_pinned_at` / `server_pk_successor_pinned_at`, in one aggregate
      query, pinned by query count as `_latest_samples` already is.
- [ ] `ServerKeyRotationPanel` on Agents: idle and active states, countdown, adoption
      rollup, Rotate disabled during an overlap and a 409 handled as a refetch.
- [ ] Per-agent key-state column, shown only during an overlap.
- [ ] Rotation runbook; INC-13 marked Resolved.

**Verification:** Adoption counts stay one query as the fleet grows; the panel never
claims an agent *holds* the successor key, only that its handshakes have used it.

## Slice UI-3 — Audit view and chain integrity

**Supports:** INC-12
**Depends on:** UI-2 (`HighRiskConfirmDialog`)

- [ ] `/logs/audit` route rendering `LogsPage` in `auditMode`, pinned to `category=audit`.
- [ ] `AuditChainPanel` — quiet when intact, escalated when broken, Repair behind the
      `REPAIR_AUDIT_CHAIN` phrase and a ≥12-character reason taken from the server contract.
- [ ] Refetch verify and the log list after repair, so the repair entry appears in view.
- [ ] Disposition for `GET /logs/audit` as redundant with `GET /logs?category=audit`.
- [ ] `docs/audit-log.md:48` corrected; INC-12 marked Resolved.

**Verification:** The panel renders the broken state from a `valid: false` response;
`LogsPage`'s existing tests do not regress.

## Slice UI-4 — Business Intelligence

**Supports:** INC-10
**Depends on:** nothing

- [ ] Include asset names in `CapacityForecastOut` and `ResourceEfficiencyOut`.
- [ ] Make "the analytics job has not run" distinguishable from "nothing to report".
- [ ] `/intel` page with both ranked tables, visible to all authenticated users.
- [ ] `BlastRadiusPanel` on Hardware, Compute, Service, and Storage detail views,
      fetching on expand, with zero impact rendered as an answer.
- [ ] `docs/business_intelligence.md:5-6` updated; INC-10 marked Resolved.

**Verification:** No table renders a bare integer where an asset name belongs; the empty
state names the job and its schedule.

## Slice UI-5 — Access tokens and service accounts

**Supports:** INC-14, and closes INC-04
**Depends on:** UI-2 (`HighRiskConfirmDialog`)

- [ ] **B1** — `require_role` honours token scopes, covering the `uid == 0` early return.
      Back-compat: stored `scopes == []` means "unscoped, inherit the creator", implemented
      in `_normalise_token_scopes`, which also closes INC-04's 403 for existing rows.
- [ ] **B2** — validate scopes against a catalog; reject unknown values and empty lists.
- [ ] **B3** — shared scope catalog and `GET /auth/scopes`.
- [ ] **B4** — `POST /auth/api-token` accepts scopes (INC-04's fix for new tokens).
- [ ] **B5** — `APITokenItem` gains scopes, creator, and an explicit service-account flag.
- [ ] **B6** — drop the `created_by` filter for admins on list **and** delete.
- [ ] **B7** — token rotation endpoint.
- [ ] `AccessTokensManager` in Settings → Security; `ProfileModal`'s create form retires
      to it, leaving one create path.
- [ ] Tokens and service-accounts documentation; INC-14 marked Resolved, INC-04 closed,
      and the privilege-escalation finding filed to the release-readiness audit.

**Verification:** A scoped token is refused on a `require_role` route it lacks scope for,
**and** a legacy scope-less token still authenticates as its creator. No preset claims a
granularity `require_scope` does not enforce.
