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
        labelKey: 'header.external',
      },
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
        require: 'admin',
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
        require: 'admin',
      },
      {
        path: '/admin/tokens',
        icon: KeyRound,
        label: 'Access Tokens',
        labelKey: 'header.accessTokens',
        require: 'admin',
      },
      {
        path: '/certificates',
        icon: Shield,
        label: 'Certificates',
        labelKey: 'header.certificates',
        require: 'admin',
      },
      {
        path: '/notifications',
        icon: Bell,
        label: 'Notifications',
        labelKey: 'header.notifications',
        require: 'admin',
      },
      {
        path: '/logs',
        icon: ScrollText,
        label: 'Logs',
        labelKey: 'header.logs',
        require: 'admin',
        dockDefault: true,
      },
      {
        path: '/logs/audit',
        icon: FileClock,
        label: 'Audit Log',
        labelKey: 'header.auditLog',
        require: 'admin',
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
        require: 'editor',
        dockDefault: true,
      },
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
