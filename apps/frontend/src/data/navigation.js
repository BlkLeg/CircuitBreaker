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
import { guardFor } from './routeGuards';

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
 *   require     derived from data/routeGuards.js — never declared here
 *   dockDefault in a fresh install's dock
 */
export const NAV_GROUPS = [
  {
    id: 'acquire',
    label: 'Acquire',
    labelKey: 'header.groupAcquire',
    items: [
      {
        path: '/discovery',
        icon: ScanSearch,
        label: 'Discovery',
        labelKey: 'header.discovery',
        dockDefault: true,
      },
      {
        path: '/agents',
        icon: Satellite,
        label: 'Agents',
        labelKey: 'header.agents',
        dockDefault: true,
      },
    ],
  },
  {
    id: 'inventory',
    label: 'Inventory',
    labelKey: 'header.groupInventory',
    items: [
      {
        path: '/hardware',
        icon: Cpu,
        label: 'Hardware',
        labelKey: 'header.hardware',
        dockDefault: true,
      },
      {
        path: '/compute-units',
        icon: Server,
        label: 'Compute',
        labelKey: 'header.compute',
        dockDefault: true,
      },
      {
        path: '/services',
        icon: Layers,
        label: 'Services',
        labelKey: 'header.services',
        dockDefault: true,
      },
      { path: '/storage', icon: HardDrive, label: 'Storage', labelKey: 'header.storage' },
      {
        path: '/external-nodes',
        icon: Cloud,
        label: 'External Nodes',
        labelKey: 'header.externalNodes',
      },
      { path: '/ipam', icon: Globe, label: 'IPAM', labelKey: 'header.ipam' },
      { path: '/misc', icon: Boxes, label: 'Other Assets', labelKey: 'header.otherAssets' },
    ],
  },
  {
    id: 'observe',
    label: 'Observe',
    labelKey: 'header.groupObserve',
    items: [
      { path: '/map', icon: Map, label: 'Map', labelKey: 'header.map', dockDefault: true },
      {
        path: '/monitors',
        icon: Activity,
        label: 'Monitors',
        labelKey: 'header.monitors',
        dockDefault: true,
      },
      { path: '/intel', icon: TrendingUp, label: 'Intel', labelKey: 'header.intel' },
      {
        path: '/privacy',
        icon: ShieldCheck,
        label: 'Privacy',
        labelKey: 'header.privacy',
      },
    ],
  },
  {
    id: 'govern',
    label: 'Govern',
    labelKey: 'header.groupGovern',
    items: [
      {
        path: '/admin/users',
        icon: Users,
        label: 'Users',
        labelKey: 'header.users',
      },
      {
        path: '/admin/tokens',
        icon: KeyRound,
        label: 'Access Tokens',
        labelKey: 'header.accessTokens',
      },
      {
        path: '/certificates',
        icon: Shield,
        label: 'Certificates',
        labelKey: 'header.certificates',
      },
      {
        path: '/notifications',
        icon: Bell,
        label: 'Notifications',
        labelKey: 'header.notifications',
      },
      {
        path: '/logs',
        icon: ScrollText,
        label: 'Logs',
        labelKey: 'header.logs',
        dockDefault: true,
      },
      {
        path: '/logs/audit',
        icon: FileClock,
        label: 'Audit Log',
        labelKey: 'header.auditLog',
      },
    ],
  },
  {
    id: 'system',
    label: 'System',
    labelKey: 'header.groupSystem',
    items: [
      {
        path: '/settings',
        icon: Settings,
        label: 'Settings',
        labelKey: 'header.settings',
        dockDefault: true,
      },
      { path: '/docs', icon: BookOpen, label: 'Docs', labelKey: 'header.docs' },
    ],
  },
];

/** Every item, declaration order preserved, tagged with its group id and route guard. */
export const NAV_ITEMS_FLAT = NAV_GROUPS.flatMap((group) =>
  group.items.map((item) => ({ ...item, groupId: group.id, require: guardFor(item.path) }))
);

/** path → item. */
export const NAV_MAP = Object.fromEntries(NAV_ITEMS_FLAT.map((item) => [item.path, item]));

/** path → the group it belongs to. */
const NAV_GROUP_OF = Object.fromEntries(
  NAV_GROUPS.flatMap((group) => group.items.map((item) => [item.path, group]))
);

/**
 * NAV_MAP lookup for a path that came from outside the code — a stored `dock_order`, a
 * URL. Both maps are plain objects, so a bare `NAV_MAP[path]` resolves `constructor` or
 * `toString` to a truthy function whose `.path` is undefined; the dock used to crash the
 * whole app on that. Every consumer of an untrusted path goes through here, which is also
 * why the object-injection suppression exists once rather than at each call site.
 */
export function navItem(path) {
  // eslint-disable-next-line security/detect-object-injection -- own-property checked above
  return Object.hasOwn(NAV_MAP, path) ? NAV_MAP[path] : null;
}

/** The group a path belongs to, or null. Same guard, same reason, as navItem. */
export function navGroupOf(path) {
  // eslint-disable-next-line security/detect-object-injection -- own-property checked above
  return Object.hasOwn(NAV_GROUP_OF, path) ? NAV_GROUP_OF[path] : null;
}

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
 *
 * The item's gate is read from its path and from nothing else: callers pass raw
 * NAV_GROUPS items (the palette, the dock picker) as readily as derived ones, and a
 * shape that had lost `require` on the way here would silently open the entry to
 * everyone. guardFor is the same answer the router gives that path, and it answers
 * for a path it does not know too — so an item without a resolvable path goes through
 * the same lookup as every other item rather than falling back to a `require` the
 * caller supplied, which is the one input that could be more permissive than the route.
 */
export function canSeeNavItem(item, group, user) {
  const gates = [group?.require, guardFor(item?.path)];
  for (const gate of gates) {
    if (gate === 'admin' && !isAdmin(user)) return false;
    if (gate === 'editor' && !canEdit(user)) return false;
  }
  return true;
}

/** NAV_GROUPS filtered for a user; groups left empty are dropped. */
export function visibleNavGroups(user) {
  return NAV_GROUPS.map((group) => {
    const items = group.items
      .map((item) => ({ ...item, require: guardFor(item.path) }))
      .filter((item) => canSeeNavItem(item, group, user));
    return items.length > 0 ? { ...group, items } : null;
  }).filter(Boolean);
}

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
  // Stored verbatim, but de-duplicated: dock_order is admin-writable through the API
  // with no allowlist, and a repeated path renders the same icon twice under the same
  // React key. The UI cannot produce one; a hand-written PUT /settings can.
  if (Array.isArray(order)) return [...new Set(order)];

  const legacyHidden = settings?.dock_hidden_items;
  if (Array.isArray(legacyHidden)) {
    const hidden = new Set(legacyHidden);
    return LEGACY_DOCK_DEFAULTS.filter((path) => !hidden.has(path));
  }

  return DEFAULT_DOCK_ITEMS;
}
