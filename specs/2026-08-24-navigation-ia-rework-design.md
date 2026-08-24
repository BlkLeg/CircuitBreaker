# Navigation Information-Architecture Rework — Design

**Date:** 2026-08-24
**Status:** Approved design, not yet implemented
**Branch context:** `dev` at `25cc8684`; the INC-10 / INC-14 UI work is in flight.
**Scope:** The application's navigation layer — the hamburger "Routes" menu, the dock,
the dock preferences panel, the command palette's navigation entries, and the
page-vs-Settings-tab boundary. No page internals are redesigned.

## 1. Problem

The register in `docs/1.0.0-incomplete-features.md` tracks five findings whose fix is
"this capability has no UI": INC-10 (Intel), INC-11 (Knowledge Base), INC-12 (audit
chain), INC-13 (agent key rotation), INC-14 (scoped service accounts / token admin).
Four have landed and each landed wherever was cheapest — Intel became a top-level
route appended to an already-long group, Audit became a second Logs entry, KB became a
Settings tab, key rotation became a panel inside the Agents page. INC-14 has no
defensible home under the current taxonomy, which is what surfaced this.

Two independent defects underlie that.

### 1.1 There is no single source of navigation truth

Five surfaces each maintain their own list:

| Surface | Source | Contents |
|---|---|---|
| Hamburger menu | `NAV_ITEMS` — `apps/frontend/src/data/navigation.js:27` | 19 items, 3 groups |
| Dock | `ORIGINAL_DOCK_ORDER` — `apps/frontend/src/components/MacOSDOCK.jsx:16` | 14 hardcoded paths |
| Dock preferences | `DEFAULT_ORDER` — `navigation.js:132` | 18 paths |
| Command palette | `DEFAULT_ITEMS` — `apps/frontend/src/components/CommandPalette.jsx:12` | 9 "Go to" entries |
| Settings | `SETTINGS_TABS` — `apps/frontend/src/components/settings/SettingsNav.jsx:18` | 10 tabs |

They have measurably drifted:

- **Dead checkboxes.** `DockSettings` renders a toggle for every path in `DEFAULT_ORDER`,
  which includes `/agents`, `/intel`, `/privacy`, and `/notifications`. None of those are
  in `ORIGINAL_DOCK_ORDER`, so the dock cannot render them. Those four checkboxes control
  nothing.
- **A dead dock entry.** `ORIGINAL_DOCK_ORDER` lists `/networks`, which is absent from
  `NAV_MAP`; `findNavItem` returns `null` and `MacOSDOCK.jsx:113` silently drops it.
  `/networks` is itself only a redirect to `/ipam` (`App.jsx:159`).
- **An RBAC inconsistency.** `NAV_ITEMS` places Certificates inside a `requireAdmin`
  group, so the hamburger hides it from non-admins. `MacOSDOCK.jsx:115-119` gates only
  `/settings`, `/ipam`, and `/logs`, so the dock shows a Certificates icon to any
  authenticated user. Two independent RBAC implementations, one of them wrong.
- **A stale contract comment.** `navigation.js:24` documents the module as feeding
  "MenuBar dropdowns and CollapsibleSidebar". Neither component exists.
- **A stale palette entry.** `CommandPalette.jsx:17` offers "Go to: Networks" →
  `/networks`. The palette has no entry for Discovery, Agents, Monitors, IPAM, Intel,
  Privacy, Certificates, Notifications, Users, or the Audit Log.
- **An unreachable page.** `/misc` renders a complete `MiscPage` backed by `miscApi`,
  with tag filtering and CRUD. It appears in no navigation surface. It is reachable only
  by typing the URL.
- **An advertised feature that does not exist.** `DockSettings.jsx:44` instructs the user
  to "Drag items in the dock itself to reorder them." `MacOSDOCK.jsx` has no drag
  handling. `navigation.js:155` re-exports `GripHorizontal` with the comment "for Dock's
  reorder button"; nothing imports it.

### 1.2 The groups have stopped predicting where a feature goes

`NAV_ITEMS` has three groups:

- **Infrastructure** — 11 items spanning three unrelated jobs: acquisition (Discovery,
  Agents), inventory (Hardware, Compute, Services, Storage, External, IPAM), and
  observation (Map, Monitors, Intel).
- **Security** — Privacy, Certificates, Notifications. `PrivacyPage.jsx` is a posture
  dashboard (score card, findings charts, attack-surface table), not a security setting.
  Notification sinks and routes are alert-delivery policy. The group name is the only
  thing these three share.
- **Administration** — Users, Logs, Audit Log, Settings, and Docs. Docs is reference
  material.

Additionally, Settings operates as a second navigation: `SettingsPage.jsx:1762` renders
`<AdminUsersPage embedded />` while `/admin/users` renders the same component standalone.
One feature, two shells, two addresses, no canonical one.

## 2. Decisions

Three decisions, taken during brainstorming, constrain everything below.

**D1 — Surface roles.** The dock is a user-tunable fast lane. The hamburger is the single
complete index of every destination. Settings holds configuration and is not a navigation
surface.

**D2 — Page vs. Settings tab.** If an operator manages the records *as the job*, it is a
top-level page. If the records exist only to shape other pages, it is a Settings tab.
Applied mechanically, this answers INC-14 (API tokens are subjects of work → page) without
a judgment call, and confirms INC-11's placement (OUI/hostname hints shape discovery
naming → tab).

**D3 — Taxonomy.** Five groups. Four are keyed to the lifecycle of a tracked thing: it is acquired,
it becomes inventory, it is observed, access to it is governed. Plus a System group for
the app itself.

## 3. Architecture

### 3.1 `navigation.js` becomes the only navigation module

It exports one structure. Every other surface derives from it.

```js
export const NAV_GROUPS = [
  {
    id: 'acquire',
    label: 'Acquire',
    labelKey: 'header.groupAcquire',
    items: [
      { path: '/discovery', icon: ScanSearch, label: 'Discovery',
        labelKey: 'header.discovery', dockDefault: true },
      { path: '/agents', icon: Satellite, label: 'Agents',
        labelKey: 'header.agents', dockDefault: true },
    ],
  },
  // ...
];
```

**Item fields:**

| Field | Meaning |
|---|---|
| `path` | Route path. Must match a `<Route path>` in `App.jsx`. |
| `icon` | `lucide-react` component. |
| `label` | English default. |
| `labelKey` | i18n key. Existing `header.*` keys are reused unchanged. |
| `require` | `'admin'` or `'editor'`, optional. Group-level `require` is also honored. |
| `dockDefault` | Whether the item is in a fresh install's dock. Default `false`. |

**Derived exports:**

| Export | Derivation | Consumer |
|---|---|---|
| `NAV_GROUPS` | source | Header, CommandPalette, DockSettings |
| `NAV_ITEMS_FLAT` | groups flattened, declaration order preserved | dock, palette |
| `NAV_MAP` | `{ [path]: item }` built from the groups | back-compat only |
| `DEFAULT_DOCK_ITEMS` | items where `dockDefault === true` | first-run dock |
| `canSeeNavItem(item, group, user)` | one RBAC predicate | all surfaces |

`ORIGINAL_DOCK_ORDER` and the standalone `DEFAULT_ORDER` are deleted. Those two lists
disagreeing with each other is the direct cause of three defects in §1.1.

### 3.2 One RBAC predicate

`canSeeNavItem` is the only place navigation RBAC is decided:

```js
export function canSeeNavItem(item, group, user) {
  if (group?.require === 'admin' && !isAdmin(user)) return false;
  if (group?.require === 'editor' && !canEdit(user)) return false;
  if (item.require === 'admin' && !isAdmin(user)) return false;
  if (item.require === 'editor' && !canEdit(user)) return false;
  return true;
}
```

`Header.jsx:36-49` and `MacOSDOCK.jsx:113-120` both call it instead of implementing their
own filters. This fixes the Certificates leak structurally rather than patching one call
site: the two surfaces can no longer disagree because there is only one answer.

Note that per-item `require` replaces the current `requireAdmin` / `requireEditor` boolean
pair. This is a mechanical rename within `navigation.js` and its three consumers; no
stored data references these names.

## 4. The taxonomy

Five groups, 21 destinations. `require` shown where it applies.

### Acquire
| Item | Path | require | dockDefault |
|---|---|---|---|
| Discovery | `/discovery` | — | yes |
| Agents | `/agents` | — | yes |

### Inventory
| Item | Path | require | dockDefault |
|---|---|---|---|
| Hardware | `/hardware` | — | yes |
| Compute | `/compute-units` | — | yes |
| Services | `/services` | — | yes |
| Storage | `/storage` | — | no |
| External Nodes | `/external-nodes` | — | no |
| IPAM | `/ipam` | editor | no |
| Other Assets | `/misc` | — | no |

### Observe
| Item | Path | require | dockDefault |
|---|---|---|---|
| Map | `/map` | — | yes |
| Monitors | `/monitors` | — | yes |
| Intel | `/intel` | — | no |
| Privacy | `/privacy` | admin | no |

### Govern
| Item | Path | require | dockDefault |
|---|---|---|---|
| Users | `/admin/users` | admin | no |
| Access Tokens | `/admin/tokens` | admin | no |
| Certificates | `/certificates` | admin | no |
| Notifications | `/notifications` | admin | no |
| Logs | `/logs` | admin | yes |
| Audit Log | `/logs/audit` | admin | yes |

### System
| Item | Path | require | dockDefault |
|---|---|---|---|
| Settings | `/settings` | editor | yes |
| Docs | `/docs` | — | no |

Nine items carry `dockDefault: true`. An admin's dock today renders thirteen
(`ORIGINAL_DOCK_ORDER` minus the dead `/networks`), so this is a deliberate reduction for
**fresh installs only** — Storage, External Nodes, IPAM, and Certificates come off the
default shelf and remain one click away in the menu. Existing installations keep the dock
they have; see §5.2.

### 4.1 Moves and their justification

- **Privacy → Observe.** It is a posture dashboard, sibling to Intel and Monitors. Filing
  it under "Security" implied it was configuration.
- **Notifications → Govern.** Sink and route management is alert-delivery policy. Its only
  relationship to Certificates was that both sounded security-adjacent.
- **Docs → System.** Reference material is not administration.
- **Intel → Observe.** Under the old taxonomy INC-10's page was appended to an 11-item
  Infrastructure list, adjacent to IPAM, which shares nothing with it.
- **`/misc` → Inventory, relabelled "Other Assets".** It tracks external SaaS, tools, and
  accounts with tags — inventory that is not infrastructure. Path, page, and API are
  unchanged; only the nav label and the fact that it has one.
- **Audit Log stays a distinct entry.** INC-12 made `/logs/audit` a real filtered view
  with its own title, CSV naming, and chain-verify panel. Collapsing it back into Logs
  would undo that finding's fix. Both sit adjacent in Govern.

### 4.2 A gap this surfaced — `require` is cosmetic for three routes

Assigning `require: 'admin'` to Privacy, Certificates, and Notifications records what the
hamburger already does today. It does **not** make those pages admin-only, and the spec
should not be read as claiming it does.

`App.jsx:160-164` registers all three with no guard:

```jsx
<Route path="/certificates" element={<CertificatesPage />} />
<Route path="/privacy" element={<PrivacyPage />} />
<Route path="/notifications" element={<NotificationsPage />} />
```

Compare `/logs`, `/logs/audit`, and `/admin/users`, which are wrapped in `RequireAdmin`,
and `/ipam` and `/settings`, which are wrapped in `RequireEditor`. Any authenticated user
who types one of the three unguarded URLs reaches the page; the backend is the only
control. That is also why the dock's missing Certificates check (§1.1) was invisible —
clicking the icon it should not have shown works.

`navigation.js` is the wrong place to fix this: hiding a menu entry is presentation, not
authorization. The correct fix is a `RequireAdmin` wrapper on each of the three routes,
plus confirmation that the corresponding backend routers enforce the same role. It is
recorded here because this rework is where it was found, and it should be raised against
`docs/1.0.0-release-readiness-audit.md` rather than absorbed into the nav work.

### 4.3 Icons for new entries

| Item | Icon | Note |
|---|---|---|
| Access Tokens | `KeyRound` | verified present in `lucide-react@0.574` |
| Other Assets | `Boxes` | verified present in `lucide-react@0.574` |

All other items keep their current icons. Privacy and Audit Log both currently use
`ShieldCheck`; since they now sit in different groups this collision is acceptable, but
Audit Log should move to `ScrollText`-family iconography if the duplication reads badly in
review.

## 5. The dock

The dock's behavior is unchanged: hover-reveal via `DOCK_TRIGGER_ZONE_PX`, the
`DOCK_HIDE_DELAY_MS` grace period, the mobile subset in `MOBILE_DOCK_ITEMS`, the discovery
pending badge, and the WebSocket status dot all stay exactly as they are. Only membership,
RBAC, and preference storage change.

### 5.1 Membership

Dock candidates are `NAV_ITEMS_FLAT` filtered by `canSeeNavItem`. Order follows group
declaration order, so the dock and the hamburger present items in the same sequence.
`DockSettings` renders its checkbox list under the same five group headings, so the two
surfaces are visibly the same list rather than two lists that happen to overlap.

### 5.2 Preference storage and migration

`dock_hidden_items` is a hide-list. It cannot express "show something that is not in the
default set", which is precisely why `DEFAULT_ORDER` was extended with items
`ORIGINAL_DOCK_ORDER` did not have — adding a checkbox was the only available lever.
Keeping the hide-list would preserve the condition that caused the drift.

It is replaced by `dock_order`: an explicit, ordered array of paths.

**No backend change is required.** `dock_order` already exists end to end and is unused:
`db/models.py:1307` (`Text`, "JSON array of path strings"), `schemas/settings.py:105` and
`:375` (read and update), the `parse_dock_order` validator at `:338`, the JSON serializer
branch in `settings_service.py:138`, and a `dock_order: null` default already sitting in
`SettingsContext.jsx:31`. No frontend code reads or writes it — it is a dormant field of
exactly the needed shape, in the same class as the orphaned routes INC-19 tracks. This
design gives it its first caller rather than adding a second field beside it.

**Read path**, following the legacy-tolerant pattern INC-06 used for plaintext sink
secrets:

1. `dock_order` is present → use it verbatim, filtered by `canSeeNavItem`.
2. `dock_order` is absent, but a `dock_hidden_items` value exists → the install predates
   this change. Derive `LEGACY_DOCK_DEFAULTS` minus those hidden paths.
3. Neither is present → fresh install. Use `DEFAULT_DOCK_ITEMS`.

In cases 2 and 3 the derived list is persisted to `dock_order` on the next save.

`LEGACY_DOCK_DEFAULTS` is the current thirteen-item dock set, carried in `navigation.js`
as migration input only and marked deletable once `dock_order` is universally written.
Without it, case 2 would silently drop four icons from the dock of every existing
install — a preference change nobody asked for, in the name of fixing preferences.

`dock_hidden_items` remains in the settings schema for one release, then is removed under
a dated ticket alongside `LEGACY_DOCK_DEFAULTS`.

### 5.3 Reorder

`dock_order` being ordered gives reorder a real implementation: up/down controls (or
drag) within `DockSettings`, where the list already renders. This retires two pieces of
dishonesty — the instruction at `DockSettings.jsx:44` that describes a gesture the dock
does not support, and the orphaned `GripHorizontal` re-export at `navigation.js:155`.

Reordering by dragging the dock itself is explicitly **not** implemented. The dock
auto-hides on mouse-out, which makes drag-to-reorder there hostile.

## 6. Settings

Applying D2 to the ten tabs in `SETTINGS_TABS`:

| Tab id | Disposition | Reason |
|---|---|---|
| `general` | stays | configuration |
| `appearance` | stays | configuration |
| `resources` | stays | environments / categories / locations are vocabulary other pages consume |
| `device-roles` | stays | classification vocabulary |
| `connectivity` | stays | configuration |
| `integrations` | stays | configuration |
| `kb` | stays | OUI and hostname hints shape discovery naming — vocabulary |
| `security` | stays | configuration |
| `system` | stays | configuration |
| `users` | **removed** | user accounts are the subject of admin work, not vocabulary |

The `users` tab is deleted, not converted to a link. `/admin/users` becomes the single
address, reachable from Govern. `SettingsPage.jsx` loses the `AdminUsersPage` import and
the `activeTab === 'users'` branch at line 1762; `SettingsNav.jsx` loses the tab
descriptor.

Settings goes from ten tabs to nine and ceases to be a competing navigation.

**Explicitly not in scope:** splitting `SettingsPage.jsx`. At roughly 1800 lines it is a
real problem, but an unrelated one, and touching it while INC-10 and INC-14 are in flight
would collide.

## 7. Command palette

`CommandPalette.jsx` drops the navigation block of `DEFAULT_ITEMS` (`:13-27`) and
generates "Go to:" entries from `NAV_GROUPS`, filtered by `canSeeNavItem`, with the group
name rendered as a section label. The palette gains the eleven destinations it currently
lacks and loses the dead `/networks` entry.

Retained hardcoded: the eight `/settings?section=` deep-links (`:34-76`) and the two
`action_fn` modal entries (`:79-80`). Settings sections are sub-page anchors, not routes;
`NAV_GROUPS` should not model Settings' internals. Entity search via `searchApi` is
untouched.

The emoji icons in `DEFAULT_ITEMS` are replaced by each item's `lucide-react` icon, so the
palette, dock, and menu show one glyph per destination.

## 8. Where the five INC surfaces land

| INC | Surface | Under this design |
|---|---|---|
| INC-10 Intel | `/intel` page | Observe |
| INC-11 Knowledge Base | Settings `kb` tab | unchanged — correct under D2 |
| INC-12 Audit Log | `/logs/audit` page | Govern, adjacent to Logs |
| INC-13 Key rotation | panel on Agents page | unchanged — correctly scoped to its object |
| INC-14 Access Tokens | **new `/admin/tokens` page** | Govern |

Four of five need no change. That is the useful signal: the taxonomy was straining but
survivable until INC-14, which needs fleet-wide token inventory, service-account creation
with a scope picker, and rotation. None of that fits `ProfileModal`'s personal-token tab,
and under the old taxonomy the only slot available was "Administration", alongside Docs.
This design gives INC-14 an address before its implementation has to invent one.

### 8.1 INC-14's actual state (updated 2026-08-24, after `ecc2bad5`)

INC-14's UI has since landed as `components/settings/AccessTokensManager.jsx` — scope
catalog, fleet-wide inventory with a mine/all toggle, service-account creation, rotation
and revocation, all wired to `api/tokens.js`. **It is imported by nothing.** It has no
route, no Settings tab, and no nav entry.

That is the condition this section was written to prevent, arriving before the rework
could land. It does not invalidate the design; it changes one task from "reserve an
address" to "mount an existing component at the address reserved for it."

The component renders a bare `<div>` with no page chrome, so it needs no `embedded` prop
of the kind `AdminUsersPage` and `KnowledgeBasePage` carry. A thin `AccessTokensPage`
wrapper supplies the page heading and the `RequireAdmin` guard, and `NAV_GROUPS` gains the
Govern entry. Its placement as a page rather than a Settings tab follows D2 unchanged:
tokens are the subject of admin work, not vocabulary that shapes other pages.

This design still does not specify the component's contents — those are INC-14's and are
already built.

## 9. Testing

| Test | Asserts | Precedent |
|---|---|---|
| Route coverage | every authenticated `<Route path>` in `App.jsx` is in exactly one nav group **or** in an explicit `UNLISTED_ROUTES` array with a stated reason | INC-11's `test_update_schemas_match_frontend_editable_columns`, which names its counterpart on both sides |
| Surface parity | for a given user role, the hamburger and the dock candidate set contain the identical items. Seeded with a **viewer** so the Certificates leak fails if reintroduced | new |
| Dock migration | a stored legacy `dock_hidden_items` produces the same visible dock as before, and `dock_order` is written through on next save | INC-06's legacy-row handling |
| Group integrity | every item has a `labelKey`; no path appears in two groups; every icon resolves | new |

`UNLISTED_ROUTES` covers detail routes (`/monitors/:id`, `/agents/:id`,
`/admin/users/:id/actions`), redirects (`/networks`, `/ip-addresses`, `/tenants`, `/`,
`/discovery/history`), and out-of-shell routes (`/invite/accept`,
`/auth/change-password`, `/reset-password`). Each entry carries a comment. `/misc`
existed unreachable for months precisely because nothing enforced this.

The existing `__tests__/audit-nav.test.js` and `__tests__/intel-nav.test.js` assert
against `NAV_ITEMS`; both are updated to `NAV_GROUPS` and to the new group names.

## 10. Out of scope

- **INC-09 (i18n).** New group labels get `labelKey`s and English defaults. The empty
  `header.json` / `map.json` namespaces and the 227 untranslated call sites are not
  addressed here.
- **`known_bugs-v1.0.0-rc.1.md` #1** — sticky navigation requiring a hard reload. A
  routing/Suspense defect, unrelated to information architecture.
- **Dock visual design.** Position, reveal behavior, sizing, and animation are unchanged.
- **Splitting `SettingsPage.jsx`.** See §6.
- **INC-19 orphaned backend routes.** Separate finding, separate dispositions.
- **Adding `RequireAdmin` to `/privacy`, `/certificates`, `/notifications`.** See §4.2.
  Authorization, not information architecture; belongs to the readiness audit.

## 11. Files touched

| File | Change |
|---|---|
| `apps/frontend/src/data/navigation.js` | rewritten as the single source; `NAV_GROUPS`, `canSeeNavItem`, derived exports; `ORIGINAL_DOCK_ORDER`/`DEFAULT_ORDER` gone; stale comment at `:24` and `GripHorizontal` export at `:155` removed |
| `apps/frontend/src/components/Header.jsx` | renders `NAV_GROUPS`; local RBAC filter at `:36-49` replaced by `canSeeNavItem` |
| `apps/frontend/src/components/MacOSDOCK.jsx` | membership derived; local RBAC at `:113-120` replaced; `dock_order` read path; behavior unchanged |
| `apps/frontend/src/components/settings/DockSettings.jsx` | grouped list, reorder controls, `dock_order` write path, corrected hint at `:44` |
| `apps/frontend/src/components/settings/SettingsNav.jsx` | `users` tab descriptor removed |
| `apps/frontend/src/pages/SettingsPage.jsx` | `AdminUsersPage` import and `activeTab === 'users'` branch at `:1762` removed |
| `apps/frontend/src/components/CommandPalette.jsx` | nav entries generated from `NAV_GROUPS`; lucide icons; `/networks` entry gone |
| `apps/frontend/src/__tests__/audit-nav.test.js` | updated to `NAV_GROUPS` |
| `apps/frontend/src/__tests__/intel-nav.test.js` | updated to `NAV_GROUPS` |
| `apps/frontend/src/__tests__/nav-coverage.test.js` | new — route coverage, surface parity, group integrity |
| `apps/frontend/src/__tests__/dock-migration.test.js` | new — legacy preference migration |
| *(no backend change)* | `dock_order` already exists unused; this design is its first caller |
| `docs/settings.md` | dock preferences section updated for reorder and `dock_order` |

## 12. Sequencing

This rework touches files the in-flight INC-10 and INC-14 work also touches. It should
land **after** INC-10's UI merges and **before** INC-14 begins, so INC-14 registers
`/admin/tokens` in `NAV_GROUPS` from the start rather than adding a nav entry that then
has to be moved.

If that ordering is not available, §3 (source of truth) and §4 (taxonomy) can land
independently of §5.2 (dock preference migration). Since §5.2 turned out to need no
backend change — `dock_order` already exists — there is no schema work gating any part of
this, and the split is purely one of review size.
