# Reachability and Authorization — Design

**Date:** 2026-08-24
**Status:** Approved design, not yet implemented
**Branch context:** `dev` at `de9ff24c`; `VERSION` = `1.0.0-rc.3`
**Register:** Batch A of the remaining findings in `docs/1.0.0-incomplete-features.md` —
the untracked guard gap from INC-21, plus INC-19 and INC-20.
**Supersedes:** `specs/2026-08-24-navigation-ia-rework-design.md` §4.2. See §2.1.

**Standing policy for 1.0.0**, set with this batch and inherited by the three that follow
(B: promises the build cannot keep, C: disaster recovery, D: i18n): *when a surface
promises more than the build delivers, remove the scaffolding and state the boundary.*
Finishing the feature is the exception and needs a reason.

## 1. Problem

Three surfaces each hold an opinion about who may do what, and they disagree.

### 1.1 The router ignores the navigation layer's declaration

`data/navigation.js` declares `require: 'admin'` for Privacy, Certificates, and
Notifications. `App.jsx` registers all three in the plain authenticated block:

```jsx
<Route path="/certificates" element={<CertificatesPage />} />   // App.jsx:161
<Route path="/privacy" element={<PrivacyPage />} />             // App.jsx:164
<Route path="/notifications" element={<NotificationsPage />} /> // App.jsx:165
```

Compare `/logs`, `/logs/audit`, `/admin/users`, `/admin/tokens` (wrapped in
`RequireAdmin`) and `/ipam`, `/settings` (wrapped in `RequireEditor`). Any authenticated
user who types one of the three URLs reaches the page. The nav hides them; the router
does not.

This was recorded during the navigation rework and deliberately deferred — nav design
§4.2, and INC-21's closing note, "Not closed, and not tracked anywhere yet". It is
tracked here.

### 1.2 The API gates disagree with both

The client-side guard is not the security boundary, so the question is what the API
enforces. At `de9ff24c`:

| Page | nav declares | router enforces | API enforces |
|---|---|---|---|
| `/certificates` | `admin` | nothing | admin — **except `GET /certificates`**, which has no role dependency (`api/certificates.py:34`) |
| `/notifications` | `admin` | nothing | viewer read / editor write (`api/notifications.py:133,142,166,192,204,255,289,295,315`) |
| `/privacy` | `admin` | nothing | **nothing** — `windscribe.router` is mounted with bare `require_auth` (`main.py:1587`) and no route declares a role |

The third row is the defect with consequence. `POST /privacy-findings/ignore` and
`DELETE /privacy-findings/ignore` (`api/windscribe.py:222,246`) are writes reachable by
any authenticated user, including a viewer. Suppressing a security finding is an
authorization decision, and there is none.

`GET /certificates` is the narrower version of the same thing: every other route in that
file requires admin, so the one that lists them was missed rather than decided.

### 1.3 The SEC-06 inventory records the weakness rather than catching it

`security/endpoint_inventory.json` carries these entries faithfully:

```json
{"path": "/api/v1/privacy-findings/ignore", "methods": ["POST"],
 "rbac_policy": "authenticated-session", "auth_policy": "authenticated"}
```

`test_full_endpoint_inventory_matches_runtime_routes` passes, because the inventory is
generated from the running app by `scripts/generate_endpoint_inventory.py`. The gate
proves the inventory *matches* runtime; it makes no claim that the policy is defensible.
A write route sitting at `authenticated-session` is exactly what it cannot see. §6.2 adds
the gate that can.

### 1.4 Routes nothing reaches, code nothing runs

INC-19 lists backend routes with no frontend caller; INC-20 lists dead client code and
tenant remnants. They belong in this batch because they are the same question one layer
down — what is reachable, and should it be. §5 and §6 give each a disposition.

**1.0.0-rc is the last moment removing a route is free.** After 1.0.0 these are a
documented API surface that scoped tokens (INC-04, INC-14) may call, and removal becomes
a breaking change. The default is therefore delete; anything kept states why.

## 2. Decisions

1. Authorization for routes is declared in one security-owned module,
   `data/routeGuards.js`. The router and the navigation layer both read it. §3.
2. Navigation *derives* its `require` from that module rather than declaring its own, so
   a menu entry can never be more permissive than the route it points at. §3.2.
3. API role gates are corrected to match the declaration, per-page as decided in §4.
   The API remains the boundary; the client guard is defense in depth and honesty.
4. Two ratchets convert this class of defect from an audit finding into a test failure.
   §6.
5. One branch. The authorization commits land first and are reviewable alone; the
   hygiene commits follow. §8.

### 2.1 Why this supersedes nav design §4.2

§4.2 ruled:

> `navigation.js` is the wrong place to fix this: hiding a menu entry is presentation,
> not authorization. The correct fix is a `RequireAdmin` wrapper on each of the three
> routes, plus confirmation that the corresponding backend routers enforce the same role.

The objection is correct and is preserved here. Reading an authorization decision out of
a presentation file means someone un-hiding a menu entry for a UX reason silently widens
access.

What §4.2's own remedy leaves in place is the drift it was written about. Three literal
`RequireAdmin` wrappers fix three instances and leave the nav and the router as two
independent lists, which is the defect the navigation rework closed for menu-vs-dock and
that INC-21 closed for route-vs-nav. The fourth page to be added gets it wrong again.

This design inverts the dependency instead of accepting either horn. Authorization gets
its own module, owned as security; presentation reads *from* it. §4.2's objection is
answered structurally rather than traded away, and the two lists become one.

## 3. Architecture

### 3.1 `data/routeGuards.js` — the authorization declaration

One map from route path to required role, covering **every** path registered in
`App.jsx`'s authenticated block, not only those that appear in navigation:

```js
export const ROUTE_GUARDS = {
  '/certificates': 'admin',
  '/notifications': 'admin',
  '/logs': 'admin',
  '/logs/audit': 'admin',
  '/admin/users': 'admin',
  '/admin/users/:id/actions': 'admin',
  '/admin/tokens': 'admin',
  '/ipam': 'editor',
  '/settings': 'editor',
  '/privacy': null,   // read is any authenticated user; writes are gated server-side
  // ...every remaining authenticated route, explicitly null
};
```

`null` is a decision, not an omission — §6.1's test rejects any `App.jsx` route absent
from this map, so adding a page forces an authorization answer at the moment it is added.

The detail routes are the reason this cannot live in `navigation.js`: `/agents/:id`,
`/monitors/:id`, and `/admin/users/:id/actions` need guards and have no menu entry.
`/admin/users/:id/actions` already carries `RequireAdmin` inline today and keeps that
role through the map.

`guardFor(path)` uses the same own-property guard as `navItem` — a bare
`ROUTE_GUARDS[path]` resolves `constructor` to a truthy value, and the reason that helper
exists in `navigation.js` applies unchanged here.

### 3.2 `navigation.js` derives `require`

`NAV_GROUPS` items drop their own `require` field; `NAV_ITEMS_FLAT` sets it from
`guardFor(item.path)`. `canSeeNavItem` is untouched — it keeps reading `item.require`,
which now has exactly one origin. `visibleNavGroups`, the dock, the palette, and dock
preferences are unchanged; they already consume the predicate rather than the field.

Group-level `require` stays supported in `canSeeNavItem` (no group uses it today).

### 3.3 `App.jsx` wraps from the same map

`RequireAdmin` and `RequireEditor` collapse into one `<Guarded path=…>` that reads
`guardFor(path)` and applies the role check, redirecting to `/map` as both do now.
Behaviour for the routes already guarded is unchanged; `/certificates` and
`/notifications` gain the guard their nav entry always claimed. `/privacy` does not — its
guard is `null` per §4, and its writes are gated server-side.

`Guarded` lives in `components/common/Guarded.jsx`, not inside `App.jsx`, so that it can be
rendered in a test. A guard asserted only by grepping `App.jsx` for `<Guarded>` is a guard
nobody has watched refuse anyone.

### 3.4 The backend is still the boundary

Every change in §4 is an API change first. The client guard stops a viewer loading a page
that would 403 in every panel; it is not what makes the page admin-only.

## 4. The role table, resolved

| Surface | Read | Write | Change |
|---|---|---|---|
| Certificates | admin | admin | `GET /certificates` gains `require_role("admin")`; nav and router already say admin |
| Notifications | admin | admin | every `/notifications` route raised from viewer/editor to admin |
| Privacy | **any authenticated** | admin | `/privacy-findings/ignore` POST and DELETE gain `require_role("admin")`; reads unchanged; nav's `require` drops to `null` |

**Notifications is a tightening.** Editors who manage sinks and routes today lose that
access. It is deliberate: sink configs carry webhook URLs, which INC-06 established are
bearer credentials for posting into a channel, and the nav has always presented the page
as admin governance.

**Privacy is a widening at the nav layer.** Dropping `require: 'admin'` means viewers
gain a Privacy entry in the menu, the dock preferences, and the command palette that they
do not see today. That is the decided outcome: the privacy score, threat alerts, and
attack surface are situational awareness that any user of the install should see, while
suppressing a finding is governance. The dashboard stops being hidden; the write stops
being open.

`GET /certificates` is a tightening in principle and almost certainly not in practice —
the page listing certificates is admin-gated on every other route it calls.

## 5. INC-19 dispositions

| Route | Disposition |
|---|---|
| `GET /graph/layouts` | Delete — plural; the singular `GET /graph/layout` is the live one |
| `GET /catalog/vendors/{v}/devices/{d}` | Delete — detail route; only the list route is used |
| `POST /branding/upload-favicon` | Delete — duplicate of `POST /assets/branding/favicon` |
| `GET/PUT /hardware/{id}/ports` | Delete — `PortEditor.jsx` writes `port_map` through `PATCH /hardware/{id}` |
| `GET /logs/audit` | Delete — strict subset of `GET /logs?category=audit`, which is what `/logs/audit` renders (INC-12) |
| `GET/POST/DELETE /node-relations` | Delete — `api/ipam.py:426`, no caller, no screen |
| `GET /hardware/groups`, `GET /hardware/orphans` | Delete — no caller, no screen planned |
| `GET /hardware/entity/{type}/{id}` | **Verify, then delete** — resolves to `api/telemetry.py`, not `hardware.py`. Confirm no live telemetry path before removing |
| `POST /maps/{id}/entities` | **Verify, then decide** — confirm how map entities are added today. Delete only if a wholesale map write covers it; keeping the only granular add route is the right call if it does not |
| `POST /discovery/self-cluster`, `GET /discovery/self-cluster/status` | Delete the two routes only — see §5.1 |

Every deletion regenerates `security/endpoint_inventory.json`
(`scripts/generate_endpoint_inventory.py --write`). INC-05 recorded that skipping this
step is what left the SEC-06 gate red on `dev`; it applies to removals as well as
additions.

### 5.1 Self-cluster is not orphaned capability

The register files self-cluster under "orphaned routes", gated by a flag with no UI
toggle. That understates it. `services/docker_discovery.py:389-400` reads
`self_cluster_enabled` and calls `autocreate_self_cluster` on every Docker discovery run:

```python
self_cluster = getattr(s, "self_cluster_enabled", False)
...
if self_cluster:
    autocreate_self_cluster(cluster_db)
```

The feature runs today for any install that set the flag through `PATCH /settings`. What
is orphaned is narrower: the two manual trigger routes (`api/discovery.py:1448,1456`),
both already `require_role("admin")`, have no frontend caller.

Disposition: **delete the two manual routes, keep the automatic path, and give
`self_cluster_enabled` the Settings toggle it never had.** `self_discovery.py`, the
`docker_discovery` call site, the column, and migration `0003_self_cluster` all stay. The
flag is already in `schemas/settings.py:193,446`, so the toggle is a Settings control over
an existing field, not a new setting.

This is the one place in the batch where the standing policy resolves toward finishing
rather than removing, because the capability is live rather than scaffolding. A flag that
is read but not settable is the inverse of INC-18, whose flag is settable but never read;
they are decided in different batches for that reason.

## 6. INC-20 dispositions

- `api/discovery.js:34` — delete `getResult`. It calls `GET /discovery/results/{id}`,
  which is not in the route table, and nothing imports it.
- `api/graph.py:348-357` — delete the first-person design deliberation ("*But wait, our
  models don't have… Checking models.py… Let's add a helper*") left above code that
  already solves the problem. The working bulk-fetch below it is untouched.
- `context/TenantContext.jsx` — replace with a single `useEffect` in `App.jsx` that clears
  the legacy localStorage key, and delete the file. A context provider wrapping the entire
  app to do one key removal is the whole of what it does. The `/tenants` → `/map` redirect
  (`App.jsx:166`) **stays**: it costs one line and bookmarks still point at it. ADR-0003
  permits inert compatibility, and this keeps the compatibility while dropping the
  provider.

## 7. Testing

### 7.1 Frontend — extend `__tests__/nav-coverage.test.js`

The file already asserts route-vs-nav coverage and dock-vs-menu parity. It gains:

- Every path in `App.jsx`'s authenticated block appears in `ROUTE_GUARDS`. A new route
  with no authorization answer fails here.
- Every `ROUTE_GUARDS` key still names a live route — the same both-directions check
  `UNLISTED_ROUTES` already gets, so the map cannot rot.
- Every path in `ROUTE_GUARDS` still names a live route, and every guard value is one the
  app enforces.
- `__tests__/guarded.test.jsx` renders `Guarded` itself against a viewer, an editor, and an
  admin: each guarded path redirects the roles it excludes and admits the ones it does not.
  `/privacy` is in the admit list for a viewer, which is §4's decision asserted rather than
  assumed.
- `NAV_MAP[path].require === guardFor(path)` for every nav item, which is the derivation
  in §3.2 asserted rather than assumed.

Verify the suite against the defect it exists for: with the `/notifications` guard
removed, the viewer-redirect case must fail naming that path.

### 7.2 Backend — a policy gate, not an inventory gate

New test beside `test_full_endpoint_inventory_matches_runtime_routes`: **no route with a
mutating method (`POST`, `PUT`, `PATCH`, `DELETE`) may carry
`rbac_policy: "authenticated-session"`** without an entry in an
`_UNGATED_WRITE_EXEMPTIONS` map that gives a reason and must still name a live route —
the same exemption shape `_UNMOUNTED_ROUTERS` (INC-05) and `UNLISTED_ROUTES` (INC-21) use.

Seed exemptions are the genuinely unauthenticated-by-design writes (login, password
change, invite accept); each states why. Verified against the defect: before §4 lands,
this test fails naming `POST /api/v1/privacy-findings/ignore`.

### 7.3 Role coverage for the three surfaces

`tests/api/` gains per-surface role tests: viewer 403 / admin 200 on the notifications
routes, viewer 403 on `POST/DELETE /privacy-findings/ignore` with viewer 200 on the
privacy reads, and viewer 403 on `GET /certificates`. These are the assertions whose
absence let the three surfaces disagree.

## 8. Sequencing

One branch, in this order:

1. **Backend gates** (§4) plus §7.3 role tests and the regenerated inventory.
2. **§7.2 policy gate** — lands after the writes it would otherwise fail on.
3. **`routeGuards.js`, `navigation.js` derivation, `App.jsx`** (§3) plus §7.1.
4. **INC-19 deletions** (§5), each with its inventory regeneration; the two verify-first
   rows resolved before their commit.
5. **Self-cluster toggle** (§5.1).
6. **INC-20 cleanups** (§6).

Steps 1–3 are the security change and are reviewable without the rest. Nothing in 4–6 is
a prerequisite for them.

## 9. Files touched

**Backend:** `api/certificates.py`, `api/notifications.py`, `api/windscribe.py`,
`api/discovery.py`, `api/graph.py`, `api/hardware.py`, `api/telemetry.py`, `api/ipam.py`,
`api/logs.py`, `api/branding.py`, `api/catalog.py`, `api/maps.py`, `main.py`,
`security/endpoint_inventory.json`, `tests/api/*`, `tests/test_router_mounting.py`.

**Frontend:** `data/routeGuards.js` (new), `components/common/Guarded.jsx` (new),
`data/navigation.js`, `App.jsx`, `api/discovery.js`, `context/TenantContext.jsx` (deleted),
`__tests__/tenant-context.test.jsx` (deleted with it), `__tests__/nav-coverage.test.js`,
`__tests__/route-guards.test.js` (new), `__tests__/guarded.test.jsx` (new), plus the
Settings control for §5.1.

**Docs:** `docs/1.0.0-incomplete-features.md` (INC-19, INC-20, and the INC-21 note
closed), and a line in `docs/1.0.0-release-readiness-audit.md` recording the
authorization change, since the notifications tightening changes what an editor can do.

## 10. Out of scope

- **INC-07, INC-08, INC-16, INC-18** — Batch B. INC-18's unread flag is deliberately not
  decided here even though §5.1 touches its mirror image.
- **INC-15** — Batch C. **INC-09** — Batch D.
- **Backend role model changes.** `require_role` and the `ROLE_SCOPE_REQUIREMENT` ladder
  INC-04 built are used as they are; no new role is introduced.
- **`known_bugs-v1.0.0-rc.1.md` #1** — sticky navigation. Unrelated.
- **Splitting `SettingsPage.jsx`**, per nav design §6.
