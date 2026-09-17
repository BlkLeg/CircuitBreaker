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
  PackageX,
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
 * Consumers: components/Header.jsx, components/MacOSDOCK.jsx (the dock),
 * components/settings/DockSettings.jsx (dock preferences), and the global navigator.
 * None of them may keep its own list or its own role filter — see
 * specs/2026-08-24-navigation-ia-rework-design.md.
 *
 * Groups follow the lifecycle of a tracked thing: it is acquired, it becomes
 * inventory, it is observed, access to it is governed. System is the app itself.
 *
 * Item fields:
 *   id          stable semantic id; paths may gain query strings, this must not
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
        id: 'discovery',
        path: '/discovery',
        icon: ScanSearch,
        label: 'Discovery',
        labelKey: 'header.discovery',
        dockDefault: true,
        description: 'Scan the network and review discovered assets.',
        aliases: ['scan', 'onboarding', 'import', 'find devices'],
      },
      {
        id: 'agents',
        path: '/agents',
        icon: Satellite,
        label: 'Agents',
        labelKey: 'header.agents',
        dockDefault: true,
        description: 'Manage collectors and their telemetry connections.',
        aliases: ['collectors', 'probes', 'endpoints', 'telemetry'],
      },
    ],
  },
  {
    id: 'inventory',
    label: 'Inventory',
    labelKey: 'header.groupInventory',
    items: [
      {
        id: 'hardware',
        path: '/hardware',
        icon: Cpu,
        label: 'Hardware',
        labelKey: 'header.hardware',
        dockDefault: true,
        description: 'Physical servers, appliances, and devices.',
        aliases: ['servers', 'devices', 'machines', 'inventory'],
      },
      {
        id: 'compute',
        path: '/compute-units',
        icon: Server,
        label: 'Compute',
        labelKey: 'header.compute',
        dockDefault: true,
        description: 'Virtual machines and compute workloads.',
        aliases: ['vms', 'virtual machines', 'guests', 'instances'],
      },
      {
        id: 'services',
        path: '/services',
        icon: Layers,
        label: 'Services',
        labelKey: 'header.services',
        dockDefault: true,
        description: 'Applications and network services.',
        aliases: ['apps', 'ports', 'daemons', 'workloads'],
      },
      {
        id: 'storage',
        path: '/storage',
        icon: HardDrive,
        label: 'Storage',
        labelKey: 'header.storage',
        description: 'Volumes, shares, arrays, and storage systems.',
        aliases: ['disks', 'nas', 'san', 'volumes'],
      },
      {
        id: 'external-nodes',
        path: '/external-nodes',
        icon: Cloud,
        label: 'External Nodes',
        labelKey: 'header.externalNodes',
        description: 'Cloud and off-network infrastructure.',
        aliases: ['cloud', 'remote', 'external', 'saas'],
      },
      {
        id: 'ipam',
        path: '/ipam',
        icon: Globe,
        label: 'IPAM',
        labelKey: 'header.ipam',
        description: 'Networks, addresses, VLANs, and sites.',
        aliases: ['network', 'subnet', 'address', 'topology'],
      },
      {
        id: 'other-assets',
        path: '/misc',
        icon: Boxes,
        label: 'Other Assets',
        labelKey: 'header.otherAssets',
        description: 'Inventory that does not fit another asset type.',
        aliases: ['misc', 'custom assets', 'uncategorized'],
      },
    ],
  },
  {
    id: 'observe',
    label: 'Observe',
    labelKey: 'header.groupObserve',
    items: [
      {
        id: 'map',
        path: '/map',
        icon: Map,
        label: 'Map',
        labelKey: 'header.map',
        dockDefault: true,
        description: 'Explore relationships in the infrastructure topology.',
        aliases: ['topology', 'graph', 'relationships', 'network map'],
      },
      {
        id: 'monitors',
        path: '/monitors',
        icon: Activity,
        label: 'Monitors',
        labelKey: 'header.monitors',
        dockDefault: true,
        description: 'Track health, availability, and alert conditions.',
        aliases: ['health', 'uptime', 'checks', 'alerts'],
      },
      {
        id: 'intel',
        path: '/intel',
        icon: TrendingUp,
        label: 'Intel',
        labelKey: 'header.intel',
        description: 'Review vulnerability and operational intelligence.',
        aliases: ['cve', 'vulnerabilities', 'risk', 'security intelligence'],
      },
      {
        id: 'privacy',
        path: '/privacy',
        icon: ShieldCheck,
        label: 'Privacy',
        labelKey: 'header.privacy',
        description: 'Inspect privacy posture and exposed sensitive data.',
        aliases: ['pii', 'sensitive data', 'exposure', 'compliance'],
      },
    ],
  },
  {
    id: 'govern',
    label: 'Govern',
    labelKey: 'header.groupGovern',
    items: [
      {
        id: 'users',
        path: '/admin/users',
        icon: Users,
        label: 'Users',
        labelKey: 'header.users',
        description: 'Administer users, roles, and account access.',
        aliases: ['accounts', 'members', 'roles', 'permissions'],
      },
      {
        id: 'access-tokens',
        path: '/admin/tokens',
        icon: KeyRound,
        label: 'Access Tokens',
        labelKey: 'header.accessTokens',
        description: 'Create and revoke API access tokens.',
        aliases: ['api keys', 'tokens', 'credentials', 'authentication'],
      },
      {
        id: 'certificates',
        path: '/certificates',
        icon: Shield,
        label: 'Certificates',
        labelKey: 'header.certificates',
        description: 'Track TLS certificates and expiration risk.',
        aliases: ['ssl', 'tls', 'expiry', 'pki'],
      },
      {
        id: 'notifications',
        path: '/notifications',
        icon: Bell,
        label: 'Notifications',
        labelKey: 'header.notifications',
        description: 'Review alerts and notification delivery.',
        aliases: ['inbox', 'alerts', 'messages', 'delivery'],
      },
      {
        id: 'logs',
        path: '/logs',
        icon: ScrollText,
        label: 'Logs',
        labelKey: 'header.logs',
        dockDefault: true,
        description: 'Search application and infrastructure events.',
        aliases: ['events', 'activity', 'system logs', 'troubleshooting'],
      },
      {
        id: 'audit-log',
        path: '/logs/audit',
        icon: FileClock,
        label: 'Audit Log',
        labelKey: 'header.auditLog',
        description: 'Review security-sensitive administrative activity.',
        aliases: ['audit', 'history', 'changes', 'compliance'],
      },
      {
        id: 'parked-messages',
        path: '/logs/parked',
        icon: PackageX,
        label: 'Parked Messages',
        labelKey: 'header.parkedMessages',
        description: 'Recover or abandon work the message bus could not deliver.',
        aliases: ['dead letter', 'dlq', 'jetstream', 'poison', 'requeue', 'stuck', 'nats'],
      },
    ],
  },
  {
    id: 'system',
    label: 'System',
    labelKey: 'header.groupSystem',
    items: [
      {
        id: 'settings',
        path: '/settings',
        icon: Settings,
        label: 'Settings',
        labelKey: 'header.settings',
        dockDefault: true,
        description: 'Configure Circuit Breaker and integrations.',
        aliases: [
          'preferences',
          'configuration',
          'options',
          'setup',
          'inventory transfer',
          'data management',
          'import inventory',
          'export inventory',
        ],
      },
      {
        id: 'docs',
        path: '/docs',
        icon: BookOpen,
        label: 'Docs',
        labelKey: 'header.docs',
        description: 'Read product guidance and API documentation.',
        aliases: ['documentation', 'help', 'guide', 'reference'],
      },
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
