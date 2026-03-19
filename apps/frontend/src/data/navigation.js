import {
  BookOpen,
  Cloud,
  Cpu,
  GripHorizontal,
  HardDrive,
  Layers,
  Network,
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
      { path: '/networks', icon: Network, label: 'Networks', labelKey: 'header.network' },
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
      { path: '/certificates', icon: Shield, label: 'Certificates' },
      { path: '/notifications', icon: Bell, label: 'Notifications' },
      { path: '/webhooks', icon: Webhook, label: 'Webhooks' },
    ],
  },
  {
    group: 'Administration',
    items: [
      { path: '/tenants', icon: Users, label: 'Tenants', requireAdmin: true },
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
  '/networks': { icon: Network, label: 'Network', labelKey: 'header.network' },
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
  '/certificates': { icon: Shield, label: 'Certificates' },
  '/notifications': { icon: Bell, label: 'Notifications' },
  '/tenants': { icon: Users, label: 'Tenants' },
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
  '/networks',
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
