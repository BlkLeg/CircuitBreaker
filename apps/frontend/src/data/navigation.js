import {
  BookOpen,
  Cloud,
  Cpu,
  GripHorizontal,
  HardDrive,
  LayoutGrid,
  Layers,
  ScrollText,
  Server,
  Settings,
  Map,
  ScanSearch,
  Globe,
  MonitorCheck,
  RectangleHorizontal,
  Shield,
  Bell,
  Users,
  Webhook,
} from 'lucide-react';

/**
 * Grouped navigation items — used by MenuBar dropdowns and CollapsibleSidebar.
 * Each group has a label and an array of route items with RBAC flags.
 */
export const NAV_ITEMS = [
  {
    group: 'Infrastructure',
    items: [
      { path: '/map', icon: Map, label: 'Map', labelKey: 'header.map' },
      { path: '/discovery', icon: ScanSearch, label: 'Discovery', labelKey: 'header.discovery' },
      { path: '/hardware', icon: Cpu, label: 'Hardware', labelKey: 'header.hardware' },
      { path: '/compute-units', icon: Server, label: 'Compute', labelKey: 'header.compute' },
      { path: '/services', icon: Layers, label: 'Services', labelKey: 'header.services' },
      { path: '/storage', icon: HardDrive, label: 'Storage', labelKey: 'header.storage' },
      { path: '/external-nodes', icon: Cloud, label: 'External', labelKey: 'header.external' },
      { path: '/ipam', icon: Globe, label: 'IPAM', labelKey: 'header.ipam', requireEditor: true },
      {
        path: '/racks',
        icon: RectangleHorizontal,
        label: 'Racks',
        labelKey: 'header.racks',
        requireEditor: true,
      },
      {
        path: '/status-pages',
        icon: MonitorCheck,
        label: 'Status Pages',
        labelKey: 'header.status',
        requireEditor: true,
      },
    ],
  },
  {
    group: 'Security',
    requireAdmin: true,
    items: [
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
      { path: '/webhooks', icon: Webhook, label: 'Webhooks' },
    ],
  },
  {
    group: 'Administration',
    items: [
      {
        path: '/admin/users',
        icon: Users,
        label: 'Users',
        labelKey: 'header.users',
        requireAdmin: true,
      },
      {
        path: '/tenants',
        icon: LayoutGrid,
        label: 'Tenants',
        labelKey: 'header.tenants',
        requireAdmin: true,
      },
      {
        path: '/logs',
        icon: ScrollText,
        label: 'Logs',
        labelKey: 'header.logs',
        requireAdmin: true,
      },
      {
        path: '/settings',
        icon: Settings,
        label: 'Settings',
        labelKey: 'header.settings',
        requireEditor: true,
      },
      { path: '/docs', icon: BookOpen, label: 'Docs', labelKey: 'header.docs' },
    ],
  },
];

/**
 * Flat map of path → { icon, label, labelKey } — used by Dock for icon rendering.
 */
export const NAV_MAP = {
  '/hardware': { icon: Cpu, label: 'Hardware', labelKey: 'header.hardware' },
  '/compute-units': { icon: Server, label: 'Compute', labelKey: 'header.compute' },
  '/services': { icon: Layers, label: 'Services', labelKey: 'header.services' },
  '/external-nodes': { icon: Cloud, label: 'External', labelKey: 'header.external' },
  '/storage': { icon: HardDrive, label: 'Storage', labelKey: 'header.storage' },
  '/map': { icon: Map, label: 'Map', labelKey: 'header.map' },
  '/discovery': { icon: ScanSearch, label: 'Discovery', labelKey: 'header.discovery' },
  '/docs': { icon: BookOpen, label: 'Docs', labelKey: 'header.docs' },
  '/logs': { icon: ScrollText, label: 'Logs', labelKey: 'header.logs' },
  '/settings': { icon: Settings, label: 'Settings', labelKey: 'header.settings' },
  '/ipam': { icon: Globe, label: 'IPAM', labelKey: 'header.ipam' },
  '/status-pages': { icon: MonitorCheck, label: 'Status', labelKey: 'header.status' },
  '/racks': { icon: RectangleHorizontal, label: 'Racks', labelKey: 'header.racks' },
  '/certificates': { icon: Shield, label: 'Certificates', labelKey: 'header.certificates' },
  '/notifications': { icon: Bell, label: 'Notifications', labelKey: 'header.notifications' },
  '/admin/users': { icon: Users, label: 'Users', labelKey: 'header.users' },
  '/tenants': { icon: LayoutGrid, label: 'Tenants', labelKey: 'header.tenants' },
  '/webhooks': { icon: Webhook, label: 'Webhooks' },
};

/**
 * Default dock item order — used when user has no saved preference.
 */
export const DEFAULT_ORDER = [
  '/discovery',
  '/map',
  '/hardware',
  '/compute-units',
  '/services',
  '/storage',
  '/external-nodes',
  '/ipam',
  '/racks',
  '/status-pages',
  '/certificates',
  '/notifications',
  '/tenants',
  '/webhooks',
  '/docs',
  '/logs',
  '/settings',
];

// Re-export the grip icon for Dock's reorder button
export { GripHorizontal };
