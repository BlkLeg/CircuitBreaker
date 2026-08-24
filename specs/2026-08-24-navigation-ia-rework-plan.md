# Navigation IA Rework — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `navigation.js` the single source of truth for every navigation surface, regroup the app's 21 destinations into five lifecycle groups, and give the orphaned `AccessTokensManager` component a home.

**Architecture:** One exported `NAV_GROUPS` structure plus one RBAC predicate `canSeeNavItem`. The hamburger, the dock, the dock preferences panel, and the command palette all derive from it instead of maintaining their own lists. Dock membership moves from the hide-list `dock_hidden_items` to the already-existing-but-unused ordered field `dock_order`, with a legacy-tolerant read path so no existing user's dock changes on upgrade.

**Tech Stack:** React 18, react-router-dom 7, lucide-react 0.574, vitest + jsdom. Frontend only — no backend or migration work.

**Spec:** `specs/2026-08-24-navigation-ia-rework-design.md`

## Global Constraints

- **Frontend only.** No backend, schema, or migration changes. `dock_order` already exists end to end (`db/models.py:1307`, `schemas/settings.py:105` and `:375`, validator `:338`, serializer `settings_service.py:138`) and is unused.
- **No dock behavior changes.** `DOCK_TRIGGER_ZONE_PX`, `DOCK_HIDE_DELAY_MS`, `DOCK_HIT_BUFFER_PX`, `MOBILE_DOCK_ITEMS`, the discovery pending badge, and the WebSocket status dot are untouched.
- **RBAC is decided in exactly one place** — `canSeeNavItem` in `apps/frontend/src/data/navigation.js`. No surface may re-implement a role filter.
- **Group ids, in declaration order:** `acquire`, `inventory`, `observe`, `govern`, `system`. Group labels: `Acquire`, `Inventory`, `Observe`, `Govern`, `System`.
- **`require` values are the strings `'admin'` and `'editor'`** — not the old `requireAdmin` / `requireEditor` booleans.
- **Do not touch** `apps/frontend/src/pages/SettingsPage.jsx` beyond removing the `users` tab branch (Task 7). Splitting that file is explicitly out of scope.
- **Do not add `RequireAdmin` to `/privacy`, `/certificates`, or `/notifications`.** That gap is real (spec §4.2) but is authorization work belonging to the readiness audit, not this rework.
- Run tests from `apps/frontend`. Single file: `npm test -- src/__tests__/<file>`. Full suite: `npm test`.
- Commit messages follow the repo's Conventional Commits style with the finding id, e.g. `feat(nav): ... (INC-14)`.

---

### Task 1: `NAV_GROUPS` and `canSeeNavItem`

Rewrites the navigation data module. Back-compat shims keep `Header`, `MacOSDOCK`, and `DockSettings` compiling untouched; they are removed in Task 9. Because the group names change, the two existing nav tests are updated here.

**Files:**
- Modify: `apps/frontend/src/data/navigation.js` (full rewrite)
- Modify: `apps/frontend/src/__tests__/audit-nav.test.js`
- Modify: `apps/frontend/src/__tests__/intel-nav.test.js`
- Test: `apps/frontend/src/__tests__/nav-groups.test.js` (create)

**Interfaces:**
- Consumes: `canEdit`, `isAdmin` from `../utils/rbac`
- Produces:
  - `NAV_GROUPS: Array<{ id, label, labelKey, require?, items }>`
  - item shape: `{ path, icon, label, labelKey, require?, dockDefault? }`
  - `NAV_ITEMS_FLAT: Array<item & { groupId }>` — declaration order
  - `NAV_MAP: Record<path, item>`
  - `DEFAULT_DOCK_ITEMS: string[]` — 9 paths
  - `LEGACY_DOCK_DEFAULTS: string[]` — 13 paths, migration input only
  - `canSeeNavItem(item, group, user): boolean`
  - `visibleNavGroups(user): NAV_GROUPS` — groups filtered, empty groups dropped
  - Shims (removed Task 9): `NAV_ITEMS`, `DEFAULT_ORDER`

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/nav-groups.test.js`:

```js
import { describe, expect, it } from 'vitest';
import {
  NAV_GROUPS,
  NAV_ITEMS_FLAT,
  NAV_MAP,
  DEFAULT_DOCK_ITEMS,
  LEGACY_DOCK_DEFAULTS,
  canSeeNavItem,
  visibleNavGroups,
} from '../data/navigation';

const admin = { role: 'admin' };
const editor = { role: 'editor' };
const viewer = { role: 'viewer' };

describe('NAV_GROUPS structure', () => {
  it('declares the five groups in lifecycle order', () => {
    expect(NAV_GROUPS.map((g) => g.id)).toEqual([
      'acquire',
      'inventory',
      'observe',
      'govern',
      'system',
    ]);
  });

  it('holds all 21 destinations', () => {
    expect(NAV_ITEMS_FLAT).toHaveLength(21);
  });

  it('gives every item a path, icon, label and labelKey', () => {
    for (const item of NAV_ITEMS_FLAT) {
      expect(item.path.startsWith('/')).toBe(true);
      expect(typeof item.label).toBe('string');
      expect(item.label.length).toBeGreaterThan(0);
      expect(typeof item.labelKey).toBe('string');
      expect(item.icon).toBeTruthy();
    }
  });

  it('never lists a path in two groups', () => {
    const paths = NAV_ITEMS_FLAT.map((i) => i.path);
    expect(new Set(paths).size).toBe(paths.length);
  });

  it('uses only the string require values', () => {
    for (const item of NAV_ITEMS_FLAT) {
      if (item.require !== undefined) {
        expect(['admin', 'editor']).toContain(item.require);
      }
      expect(item.requireAdmin).toBeUndefined();
      expect(item.requireEditor).toBeUndefined();
    }
  });
});

describe('taxonomy placement', () => {
  const groupOf = (path) => NAV_ITEMS_FLAT.find((i) => i.path === path)?.groupId;

  it('files acquisition surfaces under acquire', () => {
    expect(groupOf('/discovery')).toBe('acquire');
    expect(groupOf('/agents')).toBe('acquire');
  });

  it('files Privacy under observe — it is a posture dashboard, not a setting', () => {
    expect(groupOf('/privacy')).toBe('observe');
  });

  it('files Intel with the other observation surfaces', () => {
    expect(groupOf('/intel')).toBe('observe');
  });

  it('files Notifications under govern, away from Certificates-as-security', () => {
    expect(groupOf('/notifications')).toBe('govern');
  });

  it('files Docs under system, not administration', () => {
    expect(groupOf('/docs')).toBe('system');
  });

  it('surfaces /misc as Other Assets under inventory', () => {
    const item = NAV_ITEMS_FLAT.find((i) => i.path === '/misc');
    expect(item.label).toBe('Other Assets');
    expect(item.groupId).toBe('inventory');
  });

  it('reserves /admin/tokens under govern for INC-14', () => {
    expect(groupOf('/admin/tokens')).toBe('govern');
  });

  it('keeps the audit log a peer entry of Logs, both under govern', () => {
    expect(groupOf('/logs')).toBe('govern');
    expect(groupOf('/logs/audit')).toBe('govern');
  });

  it('does not list /networks — it is a redirect, not a destination', () => {
    expect(NAV_ITEMS_FLAT.some((i) => i.path === '/networks')).toBe(false);
  });
});

describe('canSeeNavItem', () => {
  const find = (path) => {
    const group = NAV_GROUPS.find((g) => g.items.some((i) => i.path === path));
    return [group.items.find((i) => i.path === path), group];
  };

  it('hides admin items from viewers and editors', () => {
    const [item, group] = find('/admin/users');
    expect(canSeeNavItem(item, group, admin)).toBe(true);
    expect(canSeeNavItem(item, group, editor)).toBe(false);
    expect(canSeeNavItem(item, group, viewer)).toBe(false);
  });

  it('hides editor items from viewers only', () => {
    const [item, group] = find('/ipam');
    expect(canSeeNavItem(item, group, admin)).toBe(true);
    expect(canSeeNavItem(item, group, editor)).toBe(true);
    expect(canSeeNavItem(item, group, viewer)).toBe(false);
  });

  it('shows ungated items to everyone, including a null user', () => {
    const [item, group] = find('/map');
    expect(canSeeNavItem(item, group, viewer)).toBe(true);
    expect(canSeeNavItem(item, group, null)).toBe(true);
  });

  it('hides Certificates from viewers — the dock used to show it', () => {
    const [item, group] = find('/certificates');
    expect(canSeeNavItem(item, group, viewer)).toBe(false);
    expect(canSeeNavItem(item, group, admin)).toBe(true);
  });
});

describe('visibleNavGroups', () => {
  it('drops groups left empty by filtering', () => {
    const ids = visibleNavGroups(viewer).map((g) => g.id);
    expect(ids).not.toContain('govern');
    expect(ids).toContain('observe');
  });

  it('returns every group for an admin', () => {
    expect(visibleNavGroups(admin).map((g) => g.id)).toEqual(NAV_GROUPS.map((g) => g.id));
  });
});

describe('dock defaults', () => {
  it('defaults nine items, in declaration order', () => {
    expect(DEFAULT_DOCK_ITEMS).toEqual([
      '/discovery',
      '/agents',
      '/hardware',
      '/compute-units',
      '/services',
      '/map',
      '/monitors',
      '/logs',
      '/settings',
    ]);
  });

  it('carries the legacy thirteen for migration, without the dead /networks', () => {
    expect(LEGACY_DOCK_DEFAULTS).toHaveLength(13);
    expect(LEGACY_DOCK_DEFAULTS).not.toContain('/networks');
    expect(LEGACY_DOCK_DEFAULTS).toContain('/certificates');
  });

  it('only defaults paths that exist in NAV_MAP', () => {
    for (const path of [...DEFAULT_DOCK_ITEMS, ...LEGACY_DOCK_DEFAULTS]) {
      expect(NAV_MAP).toHaveProperty(path);
    }
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && npm test -- src/__tests__/nav-groups.test.js
```

Expected: FAIL — `NAV_GROUPS` is not exported from `../data/navigation`.

- [ ] **Step 3: Rewrite `apps/frontend/src/data/navigation.js`**

Replace the entire file with:

```js
import {
  Activity,
  Bell,
  BookOpen,
  Boxes,
  Cloud,
  Cpu,
  FileClock,
  Globe,
  HardDrive,
  KeyRound,
  Layers,
  Map,
  Satellite,
  ScanSearch,
  ScrollText,
  Server,
  Settings,
  Shield,
  ShieldCheck,
  TrendingUp,
  Users,
} from 'lucide-react';
import { canEdit, isAdmin } from '../utils/rbac';

/**
 * The single source of navigation truth.
 *
 * Consumers: components/Header.jsx (the menu), components/MacOSDOCK.jsx (the dock),
 * components/settings/DockSettings.jsx (dock preferences), components/CommandPalette.jsx.
 * None of them may keep its own list or its own role filter — see
 * specs/2026-08-24-navigation-ia-rework-design.md.
 *
 * Groups follow the lifecycle of a tracked thing: it is acquired, it becomes
 * inventory, it is observed, access to it is governed. System is the app itself.
 *
 * Item fields:
 *   path        route path; must match a <Route path> in App.jsx
 *   icon        lucide-react component
 *   label       English default
 *   labelKey    i18n key
 *   require     'admin' | 'editor' — omit for no gate
 *   dockDefault in a fresh install's dock
 */
export const NAV_GROUPS = [
  {
    id: 'acquire',
    label: 'Acquire',
    labelKey: 'header.groupAcquire',
    items: [
      { path: '/discovery', icon: ScanSearch, label: 'Discovery', labelKey: 'header.discovery', dockDefault: true },
      { path: '/agents', icon: Satellite, label: 'Agents', labelKey: 'header.agents', dockDefault: true },
    ],
  },
  {
    id: 'inventory',
    label: 'Inventory',
    labelKey: 'header.groupInventory',
    items: [
      { path: '/hardware', icon: Cpu, label: 'Hardware', labelKey: 'header.hardware', dockDefault: true },
      { path: '/compute-units', icon: Server, label: 'Compute', labelKey: 'header.compute', dockDefault: true },
      { path: '/services', icon: Layers, label: 'Services', labelKey: 'header.services', dockDefault: true },
      { path: '/storage', icon: HardDrive, label: 'Storage', labelKey: 'header.storage' },
      { path: '/external-nodes', icon: Cloud, label: 'External Nodes', labelKey: 'header.external' },
      { path: '/ipam', icon: Globe, label: 'IPAM', labelKey: 'header.ipam', require: 'editor' },
      { path: '/misc', icon: Boxes, label: 'Other Assets', labelKey: 'header.otherAssets' },
    ],
  },
  {
    id: 'observe',
    label: 'Observe',
    labelKey: 'header.groupObserve',
    items: [
      { path: '/map', icon: Map, label: 'Map', labelKey: 'header.map', dockDefault: true },
      { path: '/monitors', icon: Activity, label: 'Monitors', labelKey: 'header.monitors', dockDefault: true },
      { path: '/intel', icon: TrendingUp, label: 'Intel', labelKey: 'header.intel' },
      { path: '/privacy', icon: ShieldCheck, label: 'Privacy', labelKey: 'header.privacy', require: 'admin' },
    ],
  },
  {
    id: 'govern',
    label: 'Govern',
    labelKey: 'header.groupGovern',
    items: [
      { path: '/admin/users', icon: Users, label: 'Users', labelKey: 'header.users', require: 'admin' },
      { path: '/admin/tokens', icon: KeyRound, label: 'Access Tokens', labelKey: 'header.accessTokens', require: 'admin' },
      { path: '/certificates', icon: Shield, label: 'Certificates', labelKey: 'header.certificates', require: 'admin' },
      { path: '/notifications', icon: Bell, label: 'Notifications', labelKey: 'header.notifications', require: 'admin' },
      { path: '/logs', icon: ScrollText, label: 'Logs', labelKey: 'header.logs', require: 'admin', dockDefault: true },
      { path: '/logs/audit', icon: FileClock, label: 'Audit Log', labelKey: 'header.auditLog', require: 'admin' },
    ],
  },
  {
    id: 'system',
    label: 'System',
    labelKey: 'header.groupSystem',
    items: [
      { path: '/settings', icon: Settings, label: 'Settings', labelKey: 'header.settings', require: 'editor', dockDefault: true },
      { path: '/docs', icon: BookOpen, label: 'Docs', labelKey: 'header.docs' },
    ],
  },
];

/** Every item, declaration order preserved, tagged with its group id. */
export const NAV_ITEMS_FLAT = NAV_GROUPS.flatMap((group) =>
  group.items.map((item) => ({ ...item, groupId: group.id }))
);

/** path → item. */
export const NAV_MAP = Object.fromEntries(NAV_ITEMS_FLAT.map((item) => [item.path, item]));

/** A fresh install's dock. */
export const DEFAULT_DOCK_ITEMS = NAV_ITEMS_FLAT.filter((i) => i.dockDefault).map((i) => i.path);

/**
 * The dock as it shipped before this rework — the old ORIGINAL_DOCK_ORDER minus the
 * dead /networks entry. Migration input only: it is what an install that predates
 * `dock_order` gets, so upgrading never silently removes icons. Delete this once
 * every install has written `dock_order` at least once.
 */
export const LEGACY_DOCK_DEFAULTS = [
  '/discovery',
  '/map',
  '/hardware',
  '/compute-units',
  '/services',
  '/storage',
  '/external-nodes',
  '/ipam',
  '/monitors',
  '/certificates',
  '/docs',
  '/logs',
  '/settings',
];

/**
 * The only place navigation RBAC is decided. Header and the dock disagreeing about
 * Certificates is what this exists to make impossible.
 */
export function canSeeNavItem(item, group, user) {
  const gates = [group?.require, item?.require];
  for (const gate of gates) {
    if (gate === 'admin' && !isAdmin(user)) return false;
    if (gate === 'editor' && !canEdit(user)) return false;
  }
  return true;
}

/** NAV_GROUPS filtered for a user; groups left empty are dropped. */
export function visibleNavGroups(user) {
  return NAV_GROUPS.map((group) => {
    const items = group.items.filter((item) => canSeeNavItem(item, group, user));
    return items.length > 0 ? { ...group, items } : null;
  }).filter(Boolean);
}

/* ── Back-compat shims — removed in Task 9 once no consumer remains ─────────── */

/** @deprecated use NAV_GROUPS */
export const NAV_ITEMS = NAV_GROUPS.map((group) => ({
  group: group.label,
  ...(group.require === 'admin' ? { requireAdmin: true } : {}),
  items: group.items.map((item) => ({
    ...item,
    ...(item.require === 'admin' ? { requireAdmin: true } : {}),
    ...(item.require === 'editor' ? { requireEditor: true } : {}),
  })),
}));

/** @deprecated use DEFAULT_DOCK_ITEMS */
export const DEFAULT_ORDER = DEFAULT_DOCK_ITEMS;
```

Note the removals: the `GripHorizontal` import and its re-export are gone (nothing imported them), and the stale "MenuBar dropdowns and CollapsibleSidebar" comment is replaced by the real consumer list.

- [ ] **Step 4: Update the two existing nav tests for the new groups**

Replace `apps/frontend/src/__tests__/audit-nav.test.js` with:

```js
import { describe, expect, it } from 'vitest';
import { NAV_GROUPS, NAV_ITEMS_FLAT, DEFAULT_DOCK_ITEMS } from '../data/navigation';

describe('audit log navigation', () => {
  it('is listed under Govern, next to Logs', () => {
    const govern = NAV_GROUPS.find((g) => g.id === 'govern');
    const paths = govern.items.map((i) => i.path);
    expect(paths).toContain('/logs/audit');
    expect(Math.abs(paths.indexOf('/logs/audit') - paths.indexOf('/logs'))).toBe(1);
  });

  it('is admin-only', () => {
    const item = NAV_ITEMS_FLAT.find((i) => i.path === '/logs/audit');
    expect(item.require).toBe('admin');
  });

  it('stays out of the default dock — it is a sub-view of Logs, not a peer of Map', () => {
    expect(DEFAULT_DOCK_ITEMS).not.toContain('/logs/audit');
  });
});
```

Replace `apps/frontend/src/__tests__/intel-nav.test.js` with:

```js
import { describe, expect, it } from 'vitest';
import { NAV_ITEMS_FLAT, NAV_MAP, DEFAULT_DOCK_ITEMS } from '../data/navigation';

describe('intelligence navigation', () => {
  it('is registered as a nav item', () => {
    expect(NAV_MAP).toHaveProperty('/intel');
  });

  it('is not role-gated — the routes are readable by any authenticated user', () => {
    expect(NAV_MAP['/intel'].require).toBeUndefined();
  });

  it('sits with the other observation surfaces', () => {
    expect(NAV_ITEMS_FLAT.find((i) => i.path === '/intel').groupId).toBe('observe');
  });

  it('is reachable from the menu but off the default dock shelf', () => {
    expect(DEFAULT_DOCK_ITEMS).not.toContain('/intel');
  });
});
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd apps/frontend && npm test -- src/__tests__/nav-groups.test.js src/__tests__/audit-nav.test.js src/__tests__/intel-nav.test.js
```

Expected: PASS, all three files.

- [ ] **Step 6: Run the full suite — the shims must keep every other test green**

```bash
cd apps/frontend && npm test
```

Expected: PASS. If a test fails on the `NAV_ITEMS` shim shape, fix the shim, not the test.

- [ ] **Step 7: Commit**

```bash
git add apps/frontend/src/data/navigation.js apps/frontend/src/__tests__/nav-groups.test.js \
        apps/frontend/src/__tests__/audit-nav.test.js apps/frontend/src/__tests__/intel-nav.test.js
git commit -m "feat(nav): NAV_GROUPS and a single RBAC predicate

Five lifecycle groups replace Infrastructure/Security/Administration.
Privacy moves to Observe (it is a posture dashboard), Notifications to
Govern, Docs to System, and /misc is surfaced as Other Assets. Adds
canSeeNavItem so no surface implements its own role filter.

NAV_ITEMS and DEFAULT_ORDER remain as derived shims until their
consumers are converted."
```

---

### Task 2: Mount `AccessTokensManager` at `/admin/tokens`

`components/settings/AccessTokensManager.jsx` landed in `ecc2bad5` and is imported by nothing. Task 1 put `/admin/tokens` in Govern, so the route must exist before the menu links to it.

**Files:**
- Create: `apps/frontend/src/pages/AccessTokensPage.jsx`
- Modify: `apps/frontend/src/App.jsx` (import near the other page imports; route beside `/admin/users`)
- Test: `apps/frontend/src/__tests__/access-tokens-page.test.jsx` (create)

**Interfaces:**
- Consumes: `AccessTokensManager` (default export, no props, renders a bare `<div>`); `NAV_MAP` from Task 1
- Produces: `AccessTokensPage` default export; the route `/admin/tokens`

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/access-tokens-page.test.jsx`:

```jsx
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import AccessTokensPage from '../pages/AccessTokensPage.jsx';
import { NAV_MAP } from '../data/navigation';

vi.mock('../components/settings/AccessTokensManager', () => ({
  default: () => <div data-testid="access-tokens-manager" />,
}));

describe('AccessTokensPage', () => {
  it('renders the manager INC-14 already built', () => {
    render(<AccessTokensPage />);
    expect(screen.getByTestId('access-tokens-manager')).toBeTruthy();
  });

  it('carries a page heading, which the embedded manager does not provide', () => {
    render(<AccessTokensPage />);
    expect(screen.getByRole('heading', { name: /access tokens/i })).toBeTruthy();
  });

  it('is the destination the Govern group points at', () => {
    expect(NAV_MAP['/admin/tokens'].label).toBe('Access Tokens');
    expect(NAV_MAP['/admin/tokens'].require).toBe('admin');
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && npm test -- src/__tests__/access-tokens-page.test.jsx
```

Expected: FAIL — cannot resolve `../pages/AccessTokensPage.jsx`.

- [ ] **Step 3: Create the page**

Create `apps/frontend/src/pages/AccessTokensPage.jsx`:

```jsx
import React from 'react';
import AccessTokensManager from '../components/settings/AccessTokensManager';

/**
 * Page shell for the token administration UI built under INC-14.
 *
 * AccessTokensManager renders a bare <div> with no page chrome, so unlike
 * AdminUsersPage and KnowledgeBasePage it needs no `embedded` prop — the
 * heading lives here and the component is mounted as-is.
 */
export default function AccessTokensPage() {
  return (
    <div className="page-container">
      <div className="page-header">
        <h1>Access Tokens</h1>
        <p className="page-subtitle">
          API tokens and service accounts across every administrator, with the scopes each
          one carries.
        </p>
      </div>
      <AccessTokensManager />
    </div>
  );
}
```

- [ ] **Step 4: Register the route in `App.jsx`**

Add the import beside the other page imports:

```jsx
import AccessTokensPage from './pages/AccessTokensPage';
```

Add the route directly after the `/admin/users/:id/actions` route, matching its guard:

```jsx
<Route
  path="/admin/tokens"
  element={
    <RequireAdmin>
      <AccessTokensPage />
    </RequireAdmin>
  }
/>
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd apps/frontend && npm test -- src/__tests__/access-tokens-page.test.jsx
```

Expected: PASS, 3 tests.

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/src/pages/AccessTokensPage.jsx apps/frontend/src/App.jsx \
        apps/frontend/src/__tests__/access-tokens-page.test.jsx
git commit -m "feat(nav): mount access token administration at /admin/tokens (INC-14)

AccessTokensManager shipped in ecc2bad5 imported by nothing. It now has a
page, a RequireAdmin guard, and the Govern nav entry reserved for it."
```

---

### Task 3: Header renders `NAV_GROUPS`

**Files:**
- Modify: `apps/frontend/src/components/Header.jsx` — the `NAV_ITEMS` import, and `groupedNavItems` at `:36-49`
- Test: `apps/frontend/src/__tests__/header-nav-menu.test.jsx` (create)

**Interfaces:**
- Consumes: `visibleNavGroups` from Task 1
- Produces: nothing new

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/header-nav-menu.test.jsx`:

```jsx
import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Header from '../components/Header.jsx';

const mockUser = { current: { role: 'admin' } };

vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({
    openAuthModal: vi.fn(),
    openProfileModal: vi.fn(),
    isAuthenticated: true,
    user: mockUser.current,
  }),
}));
vi.mock('../context/SettingsContext', () => ({
  useSettings: () => ({ settings: { theme: 'dark' }, reloadSettings: vi.fn() }),
}));
vi.mock('../components/common/RecentChanges.jsx', () => ({ default: () => null }));
vi.mock('../components/ThemePalette', () => ({ default: () => null }));
vi.mock('../components/HeaderWidgets.jsx', () => ({ default: () => null }));
vi.mock('../components/auth/UserAvatar.jsx', () => ({ default: () => null }));

function openMenu(user) {
  mockUser.current = user;
  render(
    <MemoryRouter>
      <Header onOpenPalette={() => {}} />
    </MemoryRouter>
  );
  fireEvent.click(screen.getByLabelText('Open route menu'));
}

describe('header route menu', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders the five lifecycle groups for an admin', () => {
    openMenu({ role: 'admin' });
    for (const label of ['Acquire', 'Inventory', 'Observe', 'Govern', 'System']) {
      expect(screen.getByText(label)).toBeTruthy();
    }
  });

  it('shows a viewer no Govern group at all', () => {
    openMenu({ role: 'viewer' });
    expect(screen.queryByText('Govern')).toBeNull();
    expect(screen.getByText('Observe')).toBeTruthy();
  });

  it('hides Certificates from a viewer', () => {
    openMenu({ role: 'viewer' });
    expect(screen.queryByText('Certificates')).toBeNull();
  });

  it('offers Access Tokens to an admin', () => {
    openMenu({ role: 'admin' });
    expect(screen.getByText('Access Tokens')).toBeTruthy();
  });

  it('offers Other Assets, which had no menu entry before', () => {
    openMenu({ role: 'admin' });
    expect(screen.getByText('Other Assets')).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && npm test -- src/__tests__/header-nav-menu.test.jsx
```

Expected: FAIL — "Acquire" not found; the menu still renders Infrastructure / Security / Administration.

- [ ] **Step 3: Convert the Header**

Change the import at `Header.jsx:12` from:

```jsx
import { NAV_ITEMS } from '../data/navigation';
import { canEdit, isAdmin } from '../utils/rbac';
```

to:

```jsx
import { visibleNavGroups } from '../data/navigation';
```

Replace the whole `groupedNavItems` memo (`:36-49`) with:

```jsx
const groupedNavItems = useMemo(() => visibleNavGroups(user), [user]);
```

In the dropdown body, the map key and heading change from `group.group` to the group id and label:

```jsx
{groupedNavItems.map((group) => (
  <div key={group.id} style={{ marginBottom: 10 }}>
    <div
      style={{
        color: 'var(--color-text-muted)',
        fontSize: 11,
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.06em',
        padding: '4px 8px',
      }}
    >
      {group.label}
    </div>
```

Everything below that — the item buttons, hover handlers, `navigate(item.path)` — is unchanged.

`canEdit` and `isAdmin` are no longer referenced in this file; remove the import to keep lint clean.

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd apps/frontend && npm test -- src/__tests__/header-nav-menu.test.jsx
```

Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/Header.jsx apps/frontend/src/__tests__/header-nav-menu.test.jsx
git commit -m "feat(nav): render the route menu from NAV_GROUPS

The menu drops its local role filter for canSeeNavItem via
visibleNavGroups, and gains the entries that had none: Other Assets and
Access Tokens."
```

---

### Task 4: Dock derives from `NAV_GROUPS`, reads `dock_order`

**Files:**
- Modify: `apps/frontend/src/data/navigation.js` — add `resolveDockPaths`
- Modify: `apps/frontend/src/components/MacOSDOCK.jsx` — delete `ORIGINAL_DOCK_ORDER` (`:16`), `findNavItem`, `NAV_ENTRIES`, the `dockItems` memo (`:110-126`) and the `hiddenPaths` memo (`:128-131`)
- Test: `apps/frontend/src/__tests__/dock-membership.test.jsx` (create)

**Interfaces:**
- Consumes: `NAV_MAP`, `NAV_ITEMS_FLAT`, `canSeeNavItem`, `DEFAULT_DOCK_ITEMS`, `LEGACY_DOCK_DEFAULTS` from Task 1
- Produces: `resolveDockPaths(settings): string[]` — used again by Task 5

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/dock-membership.test.jsx`:

```jsx
import { describe, expect, it } from 'vitest';
import {
  resolveDockPaths,
  DEFAULT_DOCK_ITEMS,
  LEGACY_DOCK_DEFAULTS,
} from '../data/navigation';

describe('resolveDockPaths', () => {
  it('uses a stored dock_order verbatim', () => {
    const order = ['/map', '/hardware'];
    expect(resolveDockPaths({ dock_order: order })).toEqual(order);
  });

  it('honours an empty dock_order — the user hid everything', () => {
    expect(resolveDockPaths({ dock_order: [] })).toEqual([]);
  });

  it('gives a fresh install the nine defaults', () => {
    expect(resolveDockPaths({})).toEqual(DEFAULT_DOCK_ITEMS);
    expect(resolveDockPaths(null)).toEqual(DEFAULT_DOCK_ITEMS);
  });

  it('gives a legacy install the dock it already had', () => {
    expect(resolveDockPaths({ dock_hidden_items: [] })).toEqual(LEGACY_DOCK_DEFAULTS);
  });

  it('subtracts a legacy install’s hidden items rather than resetting them', () => {
    const resolved = resolveDockPaths({ dock_hidden_items: ['/storage', '/docs'] });
    expect(resolved).not.toContain('/storage');
    expect(resolved).not.toContain('/docs');
    expect(resolved).toContain('/certificates');
    expect(resolved).toHaveLength(LEGACY_DOCK_DEFAULTS.length - 2);
  });

  it('prefers dock_order when both fields are present', () => {
    const resolved = resolveDockPaths({ dock_order: ['/map'], dock_hidden_items: ['/map'] });
    expect(resolved).toEqual(['/map']);
  });
});
```

Then extend the same file with the render half. **Move these four imports up beside the
existing ones at the top of the file** — ESM allows imports only at module top level, and
`import/first` will flag them otherwise:

```jsx
import React from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
// `vi` comes from the existing `vitest` import — extend it to
// `import { describe, expect, it, vi } from 'vitest';`
```

The rest appends to the end of the file:

```jsx
const mockUser = { current: { role: 'admin' } };
const mockSettings = { current: {} };

vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => ({ user: mockUser.current }) }));
vi.mock('../context/SettingsContext', () => ({
  useSettings: () => ({ settings: mockSettings.current }),
}));
vi.mock('../hooks/useIsMobile', () => ({ useIsMobile: () => false }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (_key, opts) => opts?.defaultValue ?? _key }),
}));

async function renderDock(user, settings) {
  mockUser.current = user;
  mockSettings.current = settings;
  const { default: MacOSDOCK } = await import('../components/MacOSDOCK.jsx');
  render(
    <MemoryRouter>
      <MacOSDOCK />
    </MemoryRouter>
  );
}

describe('dock membership', () => {
  it('never shows Certificates to a viewer — it did before this rework', async () => {
    await renderDock({ role: 'viewer' }, { dock_order: ['/certificates', '/map'] });
    expect(screen.queryByText('Certificates')).toBeNull();
    expect(screen.getByText('Map')).toBeTruthy();
  });

  it('drops a stored path that is no longer a nav destination', async () => {
    await renderDock({ role: 'admin' }, { dock_order: ['/networks', '/map'] });
    expect(screen.getAllByRole('link')).toHaveLength(1);
  });

  it('shows an admin the full stored order', async () => {
    await renderDock({ role: 'admin' }, { dock_order: ['/map', '/logs', '/settings'] });
    expect(screen.getAllByRole('link')).toHaveLength(3);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && npm test -- src/__tests__/dock-membership.test.jsx
```

Expected: FAIL — `resolveDockPaths` is not exported.

- [ ] **Step 3: Add `resolveDockPaths` to `navigation.js`**

Append below `visibleNavGroups`:

```js
/**
 * The dock's stored membership, newest field first.
 *
 * `dock_order` is the ordered list this design writes. `dock_hidden_items` is the
 * pre-rework hide-list; an install that has one but not the other predates this
 * change, so it gets the dock it already had (LEGACY_DOCK_DEFAULTS minus whatever it
 * had hidden) rather than being reset to the smaller default shelf.
 */
export function resolveDockPaths(settings) {
  const order = settings?.dock_order;
  if (Array.isArray(order)) return order;

  const legacyHidden = settings?.dock_hidden_items;
  if (Array.isArray(legacyHidden)) {
    const hidden = new Set(legacyHidden);
    return LEGACY_DOCK_DEFAULTS.filter((path) => !hidden.has(path));
  }

  return DEFAULT_DOCK_ITEMS;
}
```

- [ ] **Step 4: Convert `MacOSDOCK.jsx`**

Replace the import block and the two constants at `:7-31`. Delete `ORIGINAL_DOCK_ORDER` entirely and keep `MOBILE_DOCK_ITEMS` and the three tuning constants:

```jsx
import {
  NAV_MAP,
  canSeeNavItem,
  resolveDockPaths,
  NAV_GROUPS,
} from '../data/navigation';
import { useAuth } from '../context/AuthContext.jsx';
import { useSettings } from '../context/SettingsContext';

export { NAV_MAP };
export { DEFAULT_DOCK_ITEMS as DEFAULT_ORDER } from '../data/navigation';

const GROUP_OF = Object.fromEntries(
  NAV_GROUPS.flatMap((group) => group.items.map((item) => [item.path, group]))
);
```

Delete `NAV_ENTRIES` and `findNavItem`. Replace the `dockItems` and `hiddenPaths` memos (`:110-131`) with a single memo:

```jsx
const dockItems = useMemo(() => {
  return resolveDockPaths(settings)
    .map((path) => NAV_MAP[path])
    .filter((item) => item && canSeeNavItem(item, GROUP_OF[item.path], user))
    .map((item) => ({ ...item, id: item.path.replace(/\//g, '-').slice(1) }));
}, [settings, user]);
```

`visibleItems` keeps only the mobile filter:

```jsx
const visibleItems = useMemo(
  () => (isMobile ? dockItems.filter((item) => MOBILE_DOCK_ITEMS.has(item.path)) : dockItems),
  [dockItems, isMobile]
);
```

The `id` derivation changes because `/logs/audit` and `/admin/tokens` contain a second slash; `path.replace('/', '')` would have produced `logs/audit`. The discovery badge check `item.id === 'discovery'` still holds — verify it does before moving on.

Everything from `return (` onward is unchanged.

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd apps/frontend && npm test -- src/__tests__/dock-membership.test.jsx
```

Expected: PASS, 9 tests.

- [ ] **Step 6: Run the full suite**

```bash
cd apps/frontend && npm test
```

Expected: PASS. `DockSettings` still imports `NAV_MAP` and `DEFAULT_ORDER` from `../MacOSDOCK`; both are still re-exported, so it keeps working until Task 5.

- [ ] **Step 7: Commit**

```bash
git add apps/frontend/src/data/navigation.js apps/frontend/src/components/MacOSDOCK.jsx \
        apps/frontend/src/__tests__/dock-membership.test.jsx
git commit -m "feat(nav): derive dock membership from NAV_GROUPS and dock_order

Deletes ORIGINAL_DOCK_ORDER, the second hardcoded nav list, along with
the dead /networks entry it carried and the local role filter that showed
Certificates to viewers.

Membership now reads dock_order, an ordered settings field that already
existed unused. Installs with only the legacy dock_hidden_items keep the
dock they had."
```

---

### Task 5: DockSettings — grouped list, reorder, `dock_order` write path

**Files:**
- Modify: `apps/frontend/src/components/settings/DockSettings.jsx` (substantial rewrite of the component body; the `S` style object is extended, not replaced)
- Test: `apps/frontend/src/__tests__/dock-settings.test.jsx` (create)

**Interfaces:**
- Consumes: `NAV_GROUPS`, `NAV_MAP`, `canSeeNavItem`, `resolveDockPaths` from Tasks 1 and 4
- Produces: nothing new. Writes `settingsApi.update({ dock_order })`.

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/dock-settings.test.jsx`:

```jsx
import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const update = vi.fn().mockResolvedValue({});
const mockSettings = { current: {} };

vi.mock('../api/client', () => ({ settingsApi: { update: (...a) => update(...a) } }));
vi.mock('../context/SettingsContext', () => ({
  useSettings: () => ({ settings: mockSettings.current, reloadSettings: vi.fn() }),
}));
vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => ({ user: { role: 'admin' } }) }));

import DockSettings from '../components/settings/DockSettings.jsx';

function setup(settings) {
  mockSettings.current = settings;
  render(<DockSettings />);
}

describe('dock settings', () => {
  beforeEach(() => update.mockClear());

  it('groups the list under the same headings as the menu', () => {
    setup({ dock_order: ['/map'] });
    for (const label of ['Acquire', 'Inventory', 'Observe', 'Govern', 'System']) {
      expect(screen.getByText(label)).toBeTruthy();
    }
  });

  it('offers every nav destination, not a shorter hardcoded list', () => {
    setup({ dock_order: ['/map'] });
    expect(screen.getByLabelText('Other Assets')).toBeTruthy();
    expect(screen.getByLabelText('Access Tokens')).toBeTruthy();
    expect(screen.getByLabelText('Intel')).toBeTruthy();
  });

  it('checks exactly what the dock is currently showing', () => {
    setup({ dock_order: ['/map', '/hardware'] });
    expect(screen.getByLabelText('Map').checked).toBe(true);
    expect(screen.getByLabelText('Hardware').checked).toBe(true);
    expect(screen.getByLabelText('Storage').checked).toBe(false);
  });

  it('writes dock_order, never dock_hidden_items', async () => {
    setup({ dock_order: ['/map'] });
    fireEvent.click(screen.getByLabelText('Storage'));
    fireEvent.click(screen.getByText('Save'));
    await waitFor(() => expect(update).toHaveBeenCalled());
    const payload = update.mock.calls[0][0];
    expect(payload).toHaveProperty('dock_order');
    expect(payload).not.toHaveProperty('dock_hidden_items');
    expect(payload.dock_order).toEqual(['/map', '/storage']);
  });

  it('migrates a legacy preference on first save', async () => {
    setup({ dock_hidden_items: ['/storage'] });
    expect(screen.getByLabelText('Certificates').checked).toBe(true);
    expect(screen.getByLabelText('Storage').checked).toBe(false);
    fireEvent.click(screen.getByText('Save'));
    await waitFor(() => expect(update).toHaveBeenCalled());
    expect(update.mock.calls[0][0].dock_order).not.toContain('/storage');
    expect(update.mock.calls[0][0].dock_order).toContain('/certificates');
  });

  it('moves an item up, changing the saved order', async () => {
    setup({ dock_order: ['/map', '/hardware'] });
    fireEvent.click(screen.getByLabelText('Move Hardware up'));
    fireEvent.click(screen.getByText('Save'));
    await waitFor(() => expect(update).toHaveBeenCalled());
    expect(update.mock.calls[0][0].dock_order).toEqual(['/hardware', '/map']);
  });

  it('does not tell the user to drag the dock', () => {
    setup({ dock_order: ['/map'] });
    expect(screen.queryByText(/drag items in the dock/i)).toBeNull();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && npm test -- src/__tests__/dock-settings.test.jsx
```

Expected: FAIL — no group headings; the component still renders `DEFAULT_ORDER` checkboxes and saves `dock_hidden_items`.

- [ ] **Step 3: Rewrite the component body**

Replace everything in `DockSettings.jsx` from the imports through the closing `}` of the component with:

```jsx
import React, { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { settingsApi } from '../../api/client';
import { useSettings } from '../../context/SettingsContext';
import { useAuth } from '../../context/AuthContext.jsx';
import { NAV_GROUPS, NAV_MAP, canSeeNavItem, resolveDockPaths } from '../../data/navigation';

export default function DockSettings() {
  const { settings, reloadSettings } = useSettings();
  const { user } = useAuth();
  const [saving, setSaving] = useState(false);
  const [banner, setBanner] = useState(null);
  // Ordered list of paths currently on the dock.
  const [order, setOrder] = useState([]);

  useEffect(() => {
    setOrder(resolveDockPaths(settings).filter((path) => NAV_MAP[path]));
  }, [settings]);

  const groups = useMemo(
    () =>
      NAV_GROUPS.map((group) => ({
        ...group,
        items: group.items.filter((item) => canSeeNavItem(item, group, user)),
      })).filter((group) => group.items.length > 0),
    [user]
  );

  const toggle = (path) => {
    setOrder((prev) => (prev.includes(path) ? prev.filter((p) => p !== path) : [...prev, path]));
  };

  const move = (path, delta) => {
    setOrder((prev) => {
      const from = prev.indexOf(path);
      const to = from + delta;
      if (from < 0 || to < 0 || to >= prev.length) return prev;
      const next = [...prev];
      next.splice(to, 0, next.splice(from, 1)[0]);
      return next;
    });
  };

  const handleSave = async () => {
    setSaving(true);
    setBanner(null);
    try {
      await settingsApi.update({ dock_order: order });
      await reloadSettings();
      setBanner({ type: 'success', msg: 'Dock settings saved.' });
    } catch (err) {
      setBanner({ type: 'error', msg: `Save failed: ${err.message}` });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <p style={S.hint}>
        Choose which pages appear in the dock, and the order they appear in. The dock shows
        them left to right in the order listed here.
      </p>

      {groups.map((group) => (
        <div key={group.id} style={S.group}>
          <div style={S.groupLabel}>{group.label}</div>
          <div style={S.list}>
            {group.items.map((item) => {
              const Icon = item.icon;
              const position = order.indexOf(item.path);
              const checked = position >= 0;
              return (
                <div key={item.path} style={S.item}>
                  <input
                    id={`dock-item-${item.path}`}
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggle(item.path)}
                    style={{ marginRight: 10 }}
                  />
                  <Icon size={15} style={{ marginRight: 6, color: 'var(--color-text-muted)' }} />
                  <label htmlFor={`dock-item-${item.path}`} style={{ fontSize: 13 }}>
                    {item.label}
                  </label>
                  {checked && (
                    <span style={S.moveGroup}>
                      <button
                        type="button"
                        style={S.moveBtn}
                        aria-label={`Move ${item.label} up`}
                        disabled={position === 0}
                        onClick={() => move(item.path, -1)}
                      >
                        <ChevronUp size={14} />
                      </button>
                      <button
                        type="button"
                        style={S.moveBtn}
                        aria-label={`Move ${item.label} down`}
                        disabled={position === order.length - 1}
                        onClick={() => move(item.path, 1)}
                      >
                        <ChevronDown size={14} />
                      </button>
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}

      {banner && <div style={S.banner(banner.type)}>{banner.msg}</div>}

      <button
        className="btn btn-primary btn-sm"
        style={{ marginTop: 16 }}
        onClick={handleSave}
        disabled={saving}
      >
        {saving ? 'Saving…' : 'Save'}
      </button>
    </div>
  );
}
```

The `eslint-disable security/detect-object-injection` comment on line 1 is no longer needed — the keyed `NAV_MAP[path]` lookups are gone from the render path. Remove it and confirm `npm run lint` stays clean.

Add to the existing `S` object, leaving `hint`, `list`, `item`, and `banner` in place:

```js
  group: {
    marginBottom: 14,
  },
  groupLabel: {
    color: 'var(--color-text-muted)',
    fontSize: 11,
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    marginBottom: 6,
  },
  moveGroup: {
    marginLeft: 'auto',
    display: 'flex',
    gap: 2,
  },
  moveBtn: {
    display: 'flex',
    alignItems: 'center',
    background: 'transparent',
    border: '1px solid var(--color-border)',
    borderRadius: 6,
    color: 'var(--color-text-muted)',
    cursor: 'pointer',
    padding: '2px 4px',
  },
```

`S.item` needs `cursor: 'pointer'` removed and `width: '100%'` added, since it is now a `div` containing buttons rather than a wrapping `label`.

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd apps/frontend && npm test -- src/__tests__/dock-settings.test.jsx
```

Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/settings/DockSettings.jsx \
        apps/frontend/src/__tests__/dock-settings.test.jsx
git commit -m "feat(nav): dock preferences write dock_order and support reorder

The list is grouped like the menu and offers every destination, so the
four checkboxes that controlled nothing (Agents, Intel, Privacy,
Notifications) now control real icons.

Reorder is implemented rather than described: the hint that told users to
drag the dock, which never supported dragging, is replaced by up/down
controls that write the stored order."
```

---

### Task 6: Command palette generates its navigation entries

**Files:**
- Modify: `apps/frontend/src/components/CommandPalette.jsx` — the nav block of `DEFAULT_ITEMS` (`:13-27`), the `settings-open` entry (`:29`), `visibleDefaultItems` (`:203-210`), and the icon render (`:262-263`)
- Test: `apps/frontend/src/__tests__/command-palette-nav.test.jsx` (create)

**Interfaces:**
- Consumes: `NAV_GROUPS`, `canSeeNavItem` from Task 1
- Produces: nothing new

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/command-palette-nav.test.jsx`:

```jsx
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const mockUser = { current: { role: 'admin' } };

vi.mock('../api/client', () => ({ searchApi: { search: vi.fn().mockResolvedValue({ data: [] }) } }));
vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({ openAuthModal: vi.fn(), openProfileModal: vi.fn(), user: mockUser.current }),
}));

import CommandPalette from '../components/CommandPalette.jsx';

function open(user) {
  mockUser.current = user;
  render(
    <MemoryRouter>
      <CommandPalette isOpen onClose={() => {}} />
    </MemoryRouter>
  );
}

describe('command palette navigation entries', () => {
  it('offers the destinations it used to omit', () => {
    open({ role: 'admin' });
    for (const label of ['Discovery', 'Agents', 'Monitors', 'IPAM', 'Intel', 'Access Tokens']) {
      expect(screen.getByText(`Go to: ${label}`)).toBeTruthy();
    }
  });

  it('no longer offers the dead /networks redirect', () => {
    open({ role: 'admin' });
    expect(screen.queryByText('Go to: Networks')).toBeNull();
  });

  it('hides admin destinations from a viewer', () => {
    open({ role: 'viewer' });
    expect(screen.queryByText('Go to: Logs')).toBeNull();
    expect(screen.queryByText('Go to: Access Tokens')).toBeNull();
    expect(screen.getByText('Go to: Map')).toBeTruthy();
  });

  it('keeps the settings deep-links, which are anchors rather than routes', () => {
    open({ role: 'admin' });
    expect(screen.getByText('Settings: Appearance')).toBeTruthy();
  });

  it('offers "Go to: Settings" exactly once', () => {
    open({ role: 'admin' });
    expect(screen.getAllByText('Go to: Settings')).toHaveLength(1);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && npm test -- src/__tests__/command-palette-nav.test.jsx
```

Expected: FAIL — "Go to: Discovery" not found.

- [ ] **Step 3: Generate the nav entries**

Add the import:

```jsx
import { NAV_GROUPS, canSeeNavItem } from '../data/navigation';
```

Delete the navigation block of `DEFAULT_ITEMS` (`nav-hardware` through `nav-docs`, `:13-27`).

**Also delete `settings-open`** (`:29`):

```jsx
{ id: 'settings-open', icon: '⚙️', title: 'Go to: Settings', action_url: '/settings' },
```

Its title is `Go to: Settings`, which is exactly what `NAV_GROUPS` now generates for
`/settings`. Leaving it produces two identical rows in the palette. The `settings-<section>`
deep-links and the two `action_fn` entries stay.

Above `DEFAULT_ITEMS`, add:

```jsx
// Navigation entries are generated from NAV_GROUPS so the palette cannot drift from
// the menu and the dock — it used to keep its own nine-item list, which omitted
// eleven destinations and offered a /networks redirect that no longer exists.
const NAV_COMMANDS = NAV_GROUPS.flatMap((group) =>
  group.items.map((item) => ({
    id: `nav-${item.path}`,
    icon: item.icon,
    title: `Go to: ${item.label}`,
    action_url: item.path,
    navItem: item,
    navGroup: group,
  }))
);
```

Replace `visibleDefaultItems` (`:203-210`) with:

```jsx
const visibleNavCommands = NAV_COMMANDS.filter((cmd) =>
  canSeeNavItem(cmd.navItem, cmd.navGroup, user)
);
const visibleSettingsItems = DEFAULT_ITEMS.filter((item) => {
  if ((item.id.startsWith('settings-') || item.id === 'settings-open') && !canEdit(user)) {
    return false;
  }
  return true;
});
const visibleDefaultItems = [...visibleNavCommands, ...visibleSettingsItems];
```

`isAdmin` is no longer used in this file — remove it from the `../utils/rbac` import, keeping `canEdit`.

Change the icon render (`:262-263`) so both emoji strings and lucide components work:

```jsx
{showDefaults ? (
  <span className="palette-default-icon">
    {typeof item.icon === 'string' ? item.icon : <item.icon size={15} />}
  </span>
) : (
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd apps/frontend && npm test -- src/__tests__/command-palette-nav.test.jsx
```

Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/CommandPalette.jsx \
        apps/frontend/src/__tests__/command-palette-nav.test.jsx
git commit -m "feat(nav): generate command palette navigation from NAV_GROUPS

The palette kept a fourth hardcoded list of nine destinations, missing
eleven and offering a /networks redirect. Settings deep-links stay
hardcoded — those are sub-page anchors, not routes."
```

---

### Task 7: Remove the duplicated Users tab from Settings

**Files:**
- Modify: `apps/frontend/src/components/settings/SettingsNav.jsx` — delete the `users` descriptor
- Modify: `apps/frontend/src/pages/SettingsPage.jsx` — delete the `AdminUsersPage` import (`:29`) and the `activeTab === 'users'` branch (`:1762`)
- Test: `apps/frontend/src/__tests__/settings-users-tab-removed.test.js` (create)

**Interfaces:**
- Consumes: `SETTINGS_TABS`, `NAV_MAP`
- Produces: nothing

- [ ] **Step 1: Write the failing test**

Create `apps/frontend/src/__tests__/settings-users-tab-removed.test.js`:

```js
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { SETTINGS_TABS } from '../components/settings/SettingsNav.jsx';
import { NAV_MAP } from '../data/navigation';

describe('user administration has one address', () => {
  it('is not a settings tab', () => {
    expect(SETTINGS_TABS.map((t) => t.id)).not.toContain('users');
  });

  it('is a Govern nav destination', () => {
    expect(NAV_MAP['/admin/users'].label).toBe('Users');
  });

  it('is not rendered inside SettingsPage', () => {
    const src = readFileSync(
      new URL('../pages/SettingsPage.jsx', import.meta.url),
      'utf8'
    );
    expect(src).not.toContain('AdminUsersPage');
  });

  it('leaves the other nine tabs alone', () => {
    expect(SETTINGS_TABS.map((t) => t.id)).toEqual([
      'general',
      'appearance',
      'resources',
      'device-roles',
      'connectivity',
      'integrations',
      'kb',
      'security',
      'system',
    ]);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && npm test -- src/__tests__/settings-users-tab-removed.test.js
```

Expected: FAIL — `users` is still in `SETTINGS_TABS`.

- [ ] **Step 3: Delete the tab descriptor**

In `SettingsNav.jsx`, remove this object from `SETTINGS_TABS`:

```js
  {
    id: 'users',
    label: 'Users',
    icon: Users,
    description: 'Manage accounts, roles, invites, and sessions.',
    adminOnly: true,
  },
```

`Users` is no longer referenced in that file — remove it from the `lucide-react` import.

- [ ] **Step 4: Delete the branch in `SettingsPage.jsx`**

Remove the import at `:29`:

```jsx
import AdminUsersPage from './AdminUsersPage.jsx';
```

Remove the render branch at `:1762`:

```jsx
            {activeTab === 'users' && isAdmin && <AdminUsersPage embedded />}
```

`AdminUsersPage`'s `embedded` prop stays — `KnowledgeBasePage` is still mounted with it and the prop is part of that component's own contract.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd apps/frontend && npm test -- src/__tests__/settings-users-tab-removed.test.js src/__tests__/settings-page.test.jsx
```

Expected: PASS both. If `settings-page.test.jsx` asserts a tab count or the presence of the users tab, update that assertion — the tab is deliberately gone.

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/src/components/settings/SettingsNav.jsx \
        apps/frontend/src/pages/SettingsPage.jsx \
        apps/frontend/src/__tests__/settings-users-tab-removed.test.js
git commit -m "refactor(nav): user administration has one address

SettingsPage rendered <AdminUsersPage embedded /> while /admin/users
rendered the same component standalone — one feature, two shells, no
canonical address. Settings keeps configuration; Users is a Govern page."
```

---

### Task 8: Route coverage and surface parity guards

The two tests that stop this from drifting again. They run late because they require every route in `NAV_GROUPS` to exist and `resolveDockPaths` to be in place.

**Files:**
- Test: `apps/frontend/src/__tests__/nav-coverage.test.js` (create)

**Interfaces:**
- Consumes: `NAV_GROUPS`, `NAV_MAP`, `canSeeNavItem`, `resolveDockPaths`, `visibleNavGroups` from Tasks 1 and 4; parses `App.jsx` as text
- Produces: nothing

- [ ] **Step 1: Write the test**

Create `apps/frontend/src/__tests__/nav-coverage.test.js`:

```js
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import {
  NAV_GROUPS,
  NAV_MAP,
  canSeeNavItem,
  resolveDockPaths,
  visibleNavGroups,
} from '../data/navigation';

const groupOf = (path) => NAV_GROUPS.find((g) => g.items.some((i) => i.path === path));

/**
 * Routes that deliberately have no navigation entry. Each needs a reason.
 * A new page belongs in NAV_GROUPS or here — nothing else. /misc sat
 * unreachable for months because no test made that a choice.
 */
const UNLISTED_ROUTES = {
  '/': 'redirects to /map',
  '/networks': 'redirects to /ipam',
  '/ip-addresses': 'redirects to /ipam',
  '/tenants': 'redirects to /map — ADR-0003 inert compatibility',
  '/discovery/history': 'redirect handled by DiscoveryHistoryRedirect',
  '/monitors/:id': 'detail view, reached from /monitors',
  '/agents/:id': 'detail view, reached from /agents',
  '/agents/enroll': 'enrollment flow, reached from /agents',
  '/admin/users/:id/actions': 'detail view, reached from /admin/users',
  '/invite/accept': 'entered from an emailed link, outside the app shell',
  '/auth/change-password': 'forced password change, outside the app shell',
  '/reset-password': 'entered from a link, outside the app shell',
};

function authenticatedRoutePaths() {
  const src = readFileSync(new URL('../App.jsx', import.meta.url), 'utf8');
  // AppInner's <Routes> block holds the authenticated shell; the unauthenticated
  // and bootstrap blocks below it are not navigable destinations.
  const start = src.indexOf('<Routes location={location}>');
  const end = src.indexOf('</Routes>', start);
  expect(start).toBeGreaterThan(-1);
  return [...src.slice(start, end).matchAll(/<Route\s+path="([^"]+)"/g)].map((m) => m[1]);
}

describe('every route has a home', () => {
  const paths = authenticatedRoutePaths();

  it('finds the route table', () => {
    expect(paths.length).toBeGreaterThan(20);
  });

  it.each(paths)('%s is in NAV_GROUPS or explicitly unlisted', (path) => {
    const listed = Object.hasOwn(NAV_MAP, path);
    const exempt = Object.hasOwn(UNLISTED_ROUTES, path);
    expect(
      listed || exempt,
      `${path} has no nav entry and no UNLISTED_ROUTES reason. Add it to NAV_GROUPS, or to UNLISTED_ROUTES with a reason.`
    ).toBe(true);
    // Belt and braces: an exempt route must not also be navigable.
    expect(listed && exempt).toBe(false);
  });

  it('every nav destination is a real route', () => {
    for (const path of Object.keys(NAV_MAP)) {
      expect(paths, `${path} is in NAV_GROUPS but has no <Route>`).toContain(path);
    }
  });

  it('every exemption names a route that still exists', () => {
    for (const path of Object.keys(UNLISTED_ROUTES)) {
      expect(paths, `${path} is exempted but no longer routed — delete the exemption`).toContain(
        path
      );
    }
  });
});

describe('the dock and the menu agree', () => {
  const roles = [
    ['viewer', { role: 'viewer' }],
    ['editor', { role: 'editor' }],
    ['admin', { role: 'admin' }],
  ];

  // The dock never shows what the menu hides. Before this rework the dock had its own
  // role filter and showed Certificates to viewers while the menu hid it.
  it.each(roles)('shows a %s nothing in the dock that the menu withholds', (_name, user) => {
    const menuPaths = new Set(
      visibleNavGroups(user).flatMap((g) => g.items.map((i) => i.path))
    );
    const dockPaths = resolveDockPaths({ dock_order: Object.keys(NAV_MAP) })
      .map((path) => NAV_MAP[path])
      .filter((item) => canSeeNavItem(item, groupOf(item.path), user))
      .map((item) => item.path);

    for (const path of dockPaths) {
      expect(menuPaths, `dock offers ${path} to a ${_name} but the menu does not`).toContain(
        path
      );
    }
    expect(dockPaths.length).toBe(menuPaths.size);
  });

  it('withholds Certificates from a viewer on both surfaces', () => {
    const viewer = { role: 'viewer' };
    const item = NAV_MAP['/certificates'];
    expect(canSeeNavItem(item, groupOf('/certificates'), viewer)).toBe(false);
    expect(
      visibleNavGroups(viewer).flatMap((g) => g.items.map((i) => i.path))
    ).not.toContain('/certificates');
  });
});
```

- [ ] **Step 2: Run the test**

```bash
cd apps/frontend && npm test -- src/__tests__/nav-coverage.test.js
```

Expected: PASS. If a route fails, that is the test working — add it to `NAV_GROUPS` or to `UNLISTED_ROUTES` with a real reason. Do not loosen the regex.

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/src/__tests__/nav-coverage.test.js
git commit -m "test(nav): route coverage and dock/menu parity guards

Every route now needs a NAV_GROUPS entry or a stated exemption — /misc
shipped unreachable because nothing enforced this. The parity test pins
that the dock never offers what the menu withholds, seeded with a viewer
so the Certificates leak fails if it is ever reintroduced."
```

---

### Task 9: Remove the back-compat shims

**Files:**
- Modify: `apps/frontend/src/data/navigation.js` — delete `NAV_ITEMS` and `DEFAULT_ORDER`
- Modify: `apps/frontend/src/components/MacOSDOCK.jsx` — delete the `NAV_MAP` / `DEFAULT_ORDER` re-exports

- [ ] **Step 1: Confirm nothing still imports the shims**

```bash
cd apps/frontend && grep -rn "NAV_ITEMS\b\|DEFAULT_ORDER" src/ | grep -v "NAV_ITEMS_FLAT"
```

Expected: only `data/navigation.js` itself and `components/MacOSDOCK.jsx`'s re-export line. If anything else appears, convert it before continuing.

- [ ] **Step 2: Delete the shims**

From `navigation.js`, remove the entire `Back-compat shims` section — the `NAV_ITEMS` and `DEFAULT_ORDER` exports and their header comment.

From `MacOSDOCK.jsx`, remove:

```jsx
export { NAV_MAP };
export { DEFAULT_DOCK_ITEMS as DEFAULT_ORDER } from '../data/navigation';
```

and drop `NAV_MAP` from the destructured import if it is no longer used in that file's body — it is, by the `dockItems` memo, so keep the import itself.

- [ ] **Step 3: Run the full suite**

```bash
cd apps/frontend && npm test && npm run lint
```

Expected: PASS, and lint clean. A failure here means a consumer was missed in Step 1.

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/src/data/navigation.js apps/frontend/src/components/MacOSDOCK.jsx
git commit -m "refactor(nav): drop the NAV_ITEMS and DEFAULT_ORDER shims

Every surface now reads NAV_GROUPS. navigation.js exports one structure
and one role predicate; MacOSDOCK stops re-exporting navigation data it
does not own."
```

---

### Task 10: Documentation

**Files:**
- Modify: `docs/settings.md` — the dock preferences section
- Modify: `docs/1.0.0-incomplete-features.md` — the INC-14 entry and the suggested order of work

- [ ] **Step 1: Update the dock preferences documentation**

`docs/settings.md` currently mentions the dock only as a bullet under **Appearance and
layout** (`:20`, "Dock and quick-navigation options"). Leave that bullet in place and add a
dedicated subsection immediately after the "Appearance and layout" list — that is, after
the `- Map display defaults and visibility options` line (`:21`) and before
`### Inventory helpers (Resources tab)` (`:23`):

```markdown
### The dock


Choose which pages appear in the dock and the order they appear in. The list is grouped
the same way the route menu is — Acquire, Inventory, Observe, Govern, System — and offers
every destination your role can reach. The dock renders them left to right in the order
shown, and the up/down controls beside a checked item change that order.

A fresh install starts with nine items: Discovery, Agents, Hardware, Compute, Services,
Map, Monitors, Logs, and Settings. An installation upgraded from a release before this
setting existed keeps the dock it already had, including anything it had hidden.

Preferences are stored per-installation in the `dock_order` setting.
```

The heading level is `###`, matching its siblings in that section.

- [ ] **Step 2: Update the incomplete-features register**

In `docs/1.0.0-incomplete-features.md`, add to the INC-14 section, after its existing content:

```markdown
The token administration UI shipped in `ecc2bad5` as
`components/settings/AccessTokensManager.jsx` and was initially imported by nothing. It is
now mounted at `/admin/tokens` behind `RequireAdmin`, reachable from the Govern group in
the route menu — see `specs/2026-08-24-navigation-ia-rework-design.md` §8.1.
```

- [ ] **Step 3: Verify the docs build**

```bash
mkdocs build --strict
```

Expected: no warnings. If `mkdocs` is unavailable locally, confirm both files render as valid Markdown and note that CI covers the build.

- [ ] **Step 4: Commit**

```bash
git add docs/settings.md docs/1.0.0-incomplete-features.md
git commit -m "docs(nav): dock preferences and INC-14's mounted surface"
```

---

## Verification

After Task 10, from `apps/frontend`:

```bash
npm test
npm run lint
npm run build
```

All three must pass before the branch is offered for review.

Then confirm by hand, since none of this is visible to unit tests:

1. **As an admin** — open the route menu. Five groups, 21 items. Click Other Assets and Access Tokens; both load.
2. **As a viewer** — open the route menu. No Govern group. **Check the dock: no Certificates icon.** That icon's presence is the bug this rework fixes.
3. **Dock preferences** — uncheck an item, save, reload. The dock reflects it. Move an item up, save, reload. The order holds.
4. **Upgrade path** — with a database whose `app_settings.dock_order` is `NULL` and `dock_hidden_items` holds a saved list, confirm the dock is unchanged from before the upgrade.
5. **Ctrl+K** — type "tok". "Go to: Access Tokens" appears for an admin and not for a viewer.

## Known follow-ups, deliberately not in this plan

- `/privacy`, `/certificates`, `/notifications` have no `RequireAdmin` route guard, so their admin-only menu treatment is cosmetic (spec §4.2). Belongs to `docs/1.0.0-release-readiness-audit.md`.
- `dock_hidden_items` and `LEGACY_DOCK_DEFAULTS` are removable one release after this ships.
- `SettingsPage.jsx` is ~1800 lines and wants splitting.
- INC-09: the new `header.group*`, `header.otherAssets`, and `header.accessTokens` keys have English defaults only, like the 227 call sites already in the app.
