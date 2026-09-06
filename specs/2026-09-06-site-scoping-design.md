# Site Scoping and Delegated Access — Design

**Date:** 2026-09-06
**Status:** Approved design, not yet implemented
**Branch context:** `cursor/cloud-agent-1788655984708-02nrq` at `891e0190`; `VERSION` = `0.4.0`
**Amends:** ADR 0003 — see §9. The single-tenant decision stands and is not superseded; only the
inert-columns allowance is amended.
**Sub-project:** P3 of the gap assessment in `docs/design/2026-09-05-missing-features.md`.

**What this is.** One organization, many locations. A site is an *authorization scope*, not a
security boundary between hostile parties. Everyone using the install works for the same company;
what they should not do is casually browse or accidentally modify infrastructure that is not
theirs. True tenant isolation — the MSP and hosted cases — remains deferred under ADR 0003, and
nothing here claims otherwise.

---

## 1. Problem

Circuit Breaker has four grouping concepts and no scoping. Permissions are per *resource type* —
`write:hardware`, `read:*` (`core/rbac.py:25-43`, `core/token_scopes.py:9-16`) — and never per
instance. `write:hardware:123` is not expressible. So the first thing an SMB asks for is
unavailable at any price:

> The contractor maintains the warehouse. He should not be able to read HQ's Proxmox credential,
> and he should not be able to delete an HQ switch by typing the wrong ID.

There is no way to say that today. `require_role("editor")` is install-wide, so an editor is an
editor everywhere.

### 1.1 The dormant tenancy machinery is not a head start

`tenant_id` exists on 16 of ~75 tables, all nullable. `0040_rls_policies.py` enables RLS on 14
tables but never `FORCE`s it, while the application role both owns those tables and runs with
`row_security = off` — two independent bypasses, the first of which `main.py:353-408` documents
against itself. `middleware/tenant_middleware.py:25` pins the context to `None` unconditionally,
so `db/session.py:50-69` clears `app.current_tenant` on every checkout.

**The failure mode this design must not repeat.** The surviving app-layer tenant checks
(`monitor_service.py:290-307`, `probe_eligibility.py:183-186`) compare tenant IDs only when *both*
sides are non-`NULL`. Every row is `NULL`, so every check passes. A nullable authorization key does
not fail closed; it fails silent. Every decision below that looks defensive about nulls is
defensive about precisely this.

### 1.2 `Site` is correctly named and nearly unused

`Site` (`db/models.py:2622`) has exactly one referrer in the product — `Network.site_id`
(`:1001`). CRUD lives in `api/ipam.py:347-433`; the UI is one IPAM tab. Hardware has no site, only
a free-text `location` string (`:103`).

`Environment` is the inverse: `environment_id` is a real FK on hardware, compute units and
services, threaded through roughly fifteen backend modules including the graph builder, discovery
merge, metrics and the snapshot builder.

So the concept that sounds like the scoping unit is vestigial, and the well-wired one means
something orthogonal.

---

## 2. Decision

Promote `Site` to the scoping spine. Bind users to sites with an allowlist. Enforce with explicit
query predicates guarded by a structural test.

| Question | Decision | §  |
|---|---|---|
| Scoping unit | `Site`, promoted | 3 |
| Assignment | Mandatory, `NOT NULL`, denormalized onto every scoped table | 3 |
| Binding | Global role + site allowlist; admins always unrestricted | 4 |
| Enforcement | Explicit predicates + `cb_site_policy` ratchet | 5 |
| Cross-site edges | Redacted stubs | 6 |
| Dormant `tenant_id` | Dropped from every table gaining `site_id` | 3.4, 9 |

### 2.1 Rejected alternatives

| Alternative | Reason rejected |
|---|---|
| Reuse `Environment` as the scoping unit | Wrong axis. Environments are production/staging/lab; location is orthogonal. Conflating them makes "the warehouse *and* production" inexpressible, and silently changes the meaning of data users already entered. |
| A new fifth grouping concept | Site, Environment, Cluster and Tag already overlap. A fifth needs a reason none of the four can serve, and `Site` can. |
| Scope on tags | No schema change, since tags are already generic over every entity — but tags are freeform and editable by any editor, so a scoped user could retag an asset into their own scope. The authorization key must be something the scoped user cannot reassign. |
| Per-site role matrix `(user, site) → role` | More expressive, and every check must resolve the target's site before selecting a role. The allowlist is the constant-role special case, so the matrix stays available later without invalidating this work. |
| New `site_admin` role | Grows `ROLE_HIERARCHY`, which is load-bearing in two places that must agree (`ROLE_DEFAULT_SCOPES`, `ROLE_SCOPE_REQUIREMENT`). INC-14 already reconciled those once. |
| Automatic ORM-level filter injection | Misses the queries that matter most. `_preload_edge_maps()` (`api/graph.py:86-94`) builds edges as one hand-written UNION ALL CTE; `bulk_conflict_map()` does its own pass; analytics workers query directly. Coverage would be false where it counts. |
| Postgres RLS on `site_id` | Option-B machinery for an option-A problem: a non-owner Postgres role inside a container that bundles its own Postgres, plus worker bypass roles. `0040` already shows how easily this gets neutered. Remains available later as additive defense in depth. |
| Infer existing hardware's site from IP during backfill | A migration that redistributes inventory by heuristic can be wrong at 3am with no undo. |

---

## 3. Data model

### 3.1 Scoped tables carry `site_id` directly

Not derived by join. `Service.compute_id` and `Service.hardware_id` are both nullable
(`db/models.py:839-843`), as is `Storage.hardware_id` (`:941`) — freeform-first means a service may
be recorded before its host is known, so a parentless row has nothing to join to. Only
`ComputeUnit.hardware_id` is `NOT NULL` (`:755`). Denormalizing also lets the hand-written graph
SQL filter on a column rather than a three-level join.

| Carries `site_id NOT NULL` | Stays global |
|---|---|
| `hardware`, `compute_units`, `services`, `storage` | `users`, `app_settings`, `certificates` |
| `networks` (has it; becomes `NOT NULL`), `ip_addresses`, `vlans` | `notification_sinks`, `notification_routes` |
| `hardware_clusters`, `external_nodes`, `agents` | `logs`, `audit_log` |
| `monitor_items`, `scan_jobs`, `scan_results` | `tags`, `environments`, `device_roles` |
| `credentials`, `integration_configs` | `kb_oui`, `kb_hostname`, CVE entries |

`credentials` and `integration_configs` are load-bearing. Scoping an asset while leaving its
credential global would make the rest of this design ceremonial — the HQ Proxmox password is
exactly what the warehouse contractor must not hold.

**Topologies stay global and are filtered at render.** A saved map may legitimately span sites;
scoping the map itself would cost a user the entire map for one out-of-scope node. Its contents go
through the §6 stub mechanism instead.

### 3.2 The scoped registry

One module names exactly which models are scoped and, for each, how a new row derives its site. It
is the single source of truth: the service predicates read it, and so does the ratchet (§5.3).
Adding a model without registering it is what the build failure exists to catch.

### 3.3 Maintaining the invariant

A row's site is set at creation (§7.2). Moving a parent cascades to its children in the service
layer, with an integrity test asserting no child disagrees with its parent. Deliberately not a
database trigger: triggers are the fail-safe option and `0039_audit_triggers.py` is precedent, but
approach A was chosen because explicit beats implicit, and a cascade you can read in a service is a
cascade you can debug.

### 3.4 `tenant_id` is dropped

Every table gaining `site_id` loses `tenant_id` in the same revision, and the `0040` policies go
with it. `tenants` and `tenant_members` remain so the 410 API (`api/tenants.py`) and the ADR
history stay coherent. Rationale and the ADR amendment are in §9.

---

## 4. Binding and resolution

### 4.1 `user_sites`

`user_sites(user_id, site_id)`, primary key on both — the shape `tenant_members`
(`db/models.py:2392`) already establishes, minus the per-membership role.

Restriction is an **explicit boolean on the user** — `User.site_restricted`, default `False` — not
an inference from an empty allowlist. When it is `True` the API requires at least one row in
`user_sites`.

> **The trap this closes.** Empty allowlist meaning "unrestricted" is what makes the upgrade a
> behavioral no-op. But it also means an admin who removes a restricted user's last site silently
> *promotes* them to seeing everything — §1.1's bug wearing different clothes. With an explicit
> flag, "restricted to nothing" is a 422 and never a silent grant.

Admins are always unrestricted; assigning sites to an admin is a 422 rather than a silently ignored
write, so the UI cannot imply a restriction that is not enforced. "Runs the warehouse day to day"
is an editor restricted to the warehouse, not a scoped admin.

### 4.2 `SiteScope` is a value object, not a nullable

```python
class SiteScope:
    """Which sites a request may touch. Constructed once per request."""

    @classmethod
    def unrestricted(cls) -> SiteScope: ...
    @classmethod
    def of(cls, site_ids: frozenset[int]) -> SiteScope: ...
    def apply(self, query: Select, model: type[Base]) -> Select: ...
```

Two properties carry the design:

- `apply()` is the **only** place a site predicate is written, so there is one implementation to
  review rather than one per call site.
- Reading the scope when none was resolved **raises**. An unscoped code path is a 500 in testing,
  not a silent leak in production. A nullable would fail open; this fails closed.

### 4.3 Tokens can never exceed their creator

An API token or service account inherits its creator's allowlist at mint time. Without this, a
warehouse-scoped editor mints a token and walks out of their scope. This mirrors the rule INC-04
already settled for scopes: a token created without an explicit choice carries its creator's own
permissions (`api/auth.py`, `core/security.py`).

---

## 5. Enforcement

### 5.1 Four surfaces, not one

| Surface | Treatment |
|---|---|
| REST routes | Service queries run through `scope.apply()` |
| WebSocket / SSE | `ws_topology`, `ws_telemetry`, `ws_monitors` push state never requested by ID. Predicate applies at subscription **and** at publish-filter. A stream that ignores scope leaks continuously rather than once. |
| Workers / schedulers | No request context: explicitly unrestricted, and must declare it. Reading `SiteScope` without setting one raises (§4.2). |
| Export / backup | `GET /admin/export` walks every table with `.all()` (`api/admin.py:263-290`). Stays admin-only and unrestricted — correct, but must *say so* rather than be unrestricted by omission. |

### 5.2 Declaration

Route dependencies gain `cb_site_policy`, declared exactly as `cb_authorization` already is at
`core/rbac.py:206,255` and read by `apps/backend/tests/test_endpoint_policy_inventory.py:67`.

```python
_dep.cb_site_policy = ("scoped", "hardware")   # or ("unrestricted", "<written reason>")
```

### 5.3 The ratchet

A new suite in `tests/build/` asserts:

1. **every** route declares a policy — not merely the ones that look scoped. Inference was
   rejected: `response_model` names Pydantic schemas, not ORM models, so a test deciding which
   routes "return scoped data" has to guess that mapping, and a gate that guesses wrong is silent
   in the unsafe direction. Universal declaration is also what
   `security/endpoint_policy.json` already requires of every endpoint.
2. every `scoped` declaration names a model actually in the registry;
3. every `unrestricted` declaration carries a written reason, as `security/endpoint_policy.json`
   already does for its 38 exemptions.

**Written first, against today's unscoped code, and observed failing on every affected route
before any filtering exists.** A gate nobody has watched fail is a gate nobody has tested. This is
the same discipline `apps/backend/tests/test_router_mounting.py` used — verified against the
defect it exists for.

### 5.4 Failure modes

| Situation | Response | Why |
|---|---|---|
| Fetch out-of-scope asset by ID | **404** | 403 confirms the row exists, turning sequential integer IDs into an enumeration oracle |
| Create/move an asset into a site outside the allowlist | **422**, naming the site | A genuine input error, not a hidden resource |
| Reassign an asset's site | Admin only | Otherwise a scoped user widens their own access — §2.1's tag objection, applied to the write path |
| Edit any user's allowlist | Admin only | Same |
| Restrict a user to zero sites | **422** | §4.1 |
| Delete a site holding assets | **409** with count, unless `?reassign_to=` | |
| Delete the last site | **409** | The default site must always exist |

---

## 6. Cross-site visibility

A **stub** is a node the viewer can see exists but cannot inspect: identifier, owning site's name,
and kind. No name, address, vendor, model, tags, telemetry, or drill-down.

**Edge rule.** An edge renders if at least one endpoint is in scope; the out-of-scope endpoint
becomes a stub. Edges with neither endpoint in scope are omitted — a link between two invisible
things is noise, not information.

**Stubs carry real database IDs.** The alternative, an opaque per-request token, prevents
correlating a stub across requests but breaks `GraphLayout.layout_data`, which persists node
positions keyed by node ID (`db/models.py:1292-1308`) — stubs would jump position on reload and
saved layouts would rot. The marginal disclosure is nil: the stub has already announced a device
exists at HQ, and direct fetch returns 404 regardless.

**Stubs are inert.** No status ring, no metrics, no monitors. A scoped user cannot draw an edge to
a stub, so cross-site links are created and maintained by admins (who are unrestricted by §4.1).

**Blast radius reports true impact with redacted identity.**

```json
{ "visible": [ ... ], "redacted_count": 5, "redacted_sites": ["HQ"] }
```

*"This uplink affects 12 things, 5 of them at HQ."* Truncating silently to 7 would make the tool
confidently wrong in the exact moment someone is deciding whether a maintenance window is safe.
Same shape for service dependency chains.

**Everything that aggregates or searches takes the predicate.** Search especially: unscoped
full-text search is a disclosure oracle that would make this design decorative — redacting a node
on the map while the search box returns its hostname. Dashboard counts, inventory tallies and
discovery results all reflect the caller's scope; scan jobs cannot target a network outside it. The
Prometheus gauges at `/api/v1/metrics` stay global and admin-only.

**UI.** Muted styling, a lock affordance, and a label naming the owning site. "There is something
here you cannot see" builds trust; an unexplained grey box looks like a bug and generates support
load.

---

## 7. Migration and inheritance

### 7.1 One revision, safe for a half-updated deployment

```sql
ALTER TABLE hardware ADD COLUMN site_id INTEGER NOT NULL DEFAULT <default_site_id>;
```

Old code inserting a row without knowing about sites still succeeds and lands in the default site,
which satisfies the rolling-upgrade principle without a two-release dance.

Order: create `user_sites` → create the default site → add columns with the server default →
backfill the rows `networks` already has real sites for → drop `tenant_id` and the `0040` policies.

**Backfill puts everything in one site deliberately.** "All your existing equipment is at one site;
split it when you are ready" is predictable, and splitting later is supported.

### 7.2 New rows resolve through a deterministic chain

Explicit site → the network the IP falls in (the existing `inet << cidr` match in
`services/discovery_network.py:27-84`) → the discovering agent's site → the scan job's site → the
default site. It terminates, so nothing accumulates in an unassigned pile — which is what makes a
mandatory column tenable.

### 7.3 Naming

New installs name their first site in the OOBE wizard. Existing installs take
`AppSettings.app_name` with a rename prompt at first admin login. "Default Site" reads as a
migration artifact; a single-site homelab should see their lab's name.

---

## 8. Testing

| Layer | Content |
|---|---|
| **Ratchet** (`tests/build/`) | §5.3. Written first, observed failing. |
| **Adversarial matrix** | Each scoped model × each surface (list, fetch-by-id, WS, SSE, search, export, graph, blast radius) × each role. A restricted user cannot observe an out-of-scope row. |
| **Leak detector** | Seed two sites with distinctive marker strings; exercise every endpoint as a user scoped to one; fail if a foreign marker appears in any response body. Catches the leaks nobody thought to write a test for. |
| **Migration** | Upgrade a populated database; assert every row has a site, and that an unrestricted user's experience is byte-identical to before. |
| **Token inheritance** | §4.3 — a token minted by a scoped user is scoped. |
| **Cascade integrity** | §3.3 — no child disagrees with its parent. |

---

## 9. ADR 0003 amendment

ADR 0003 is **not superseded**. Its decision — 1.0 does not support true multi-tenancy as a
security boundary, and separate trust domains require separate deployments — stands unchanged, and
this design makes no isolation claim. Site scoping is delegated access inside one trust boundary,
which is the "multiple users and RBAC inside that deployment" the ADR already endorses.

One clause is amended. ADR 0003 permits tenant-shaped columns to remain "as inert compatibility
metadata **only if they do not affect the v1 security claim**", and rejects immediate deletion as
"risky migration churn for v1."

Both conditions have changed:

- **The safety condition is no longer clearly met.** `scripts/seed_default_team.py:8-18,54-59`
  documents that assigning `tenant_id = 1` activates the RLS read rule. A column whose
  documentation explains how to switch on partial isolation over 21% of the schema is not inert.
- **The churn objection does not survive this design.** This revision rewrites those exact tables
  to add `site_id`, so dropping `tenant_id` in the same migration is marginal cost — while leaving
  it means two scoping keys side by side, one live and `NOT NULL`, one dead and nullable. That
  ambiguity is what produced the original finding.

Retained: `tenants`, `tenant_members`, the 410 `api/tenants.py`, and the migration history.

---

## 10. Out of scope

| Item | Disposition |
|---|---|
| True tenant isolation (MSP, hosted) | Deferred under ADR 0003. This design is a strict subset of the inventory work that migration would need — every table gaining `site_id` is a table that would need `tenant_id` — so it is progress toward it, not a detour. |
| Per-site role matrix | §2.1. Available later without invalidating the allowlist. |
| Postgres RLS on `site_id` | §2.1. Additive defense in depth if the threat model changes. |
| Per-site notification routing | Sinks stay global and admin-only. Revisit with P1 (metric alerting), where routing is being redesigned anyway. |
| Region → Site → Building → Rack hierarchy | Sites stay flat. Racks were deliberately removed (INC-01); reintroducing depth needs its own justification. |
| Site-scoped audit log views | Audit stays admin-only and global. |
