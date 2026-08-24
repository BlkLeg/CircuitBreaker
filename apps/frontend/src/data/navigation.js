import {
  Activity,
  BookOpen,
  Cloud,
  Cpu,
  GripHorizontal,
  HardDrive,
  Layers,
  ScrollText,
  Server,
  Settings,
  Map,
  ScanSearch,
  Globe,
  Shield,
  ShieldCheck,
  Bell,
  Users,
  Satellite,
  TrendingUp,
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
      { path: '/agents', icon: Satellite, label: 'Agents', labelKey: 'header.agents' },
      { path: '/hardware', icon: Cpu, label: 'Hardware', labelKey: 'header.hardware' },
      { path: '/compute-units', icon: Server, label: 'Compute', labelKey: 'header.compute' },
      { path: '/services', icon: Layers, label: 'Services', labelKey: 'header.services' },
      { path: '/monitors', icon: Activity, label: 'Monitors', labelKey: 'header.monitors' },
      { path: '/storage', icon: HardDrive, label: 'Storage', labelKey: 'header.storage' },
      { path: '/external-nodes', icon: Cloud, label: 'External', labelKey: 'header.external' },
      { path: '/ipam', icon: Globe, label: 'IPAM', labelKey: 'header.ipam', requireEditor: true },
      { path: '/intel', icon: TrendingUp, label: 'Intel', labelKey: 'header.intel' },
    ],
  },
  {
    group: 'Security',
    requireAdmin: true,
    items: [
      {
        path: '/privacy',
        icon: ShieldCheck,
        label: 'Privacy',
        labelKey: 'header.privacy',
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
        path: '/logs',
        icon: ScrollText,
        label: 'Logs',
        labelKey: 'header.logs',
        requireAdmin: true,
      },
      {
        path: '/logs/audit',
        icon: ShieldCheck,
        label: 'Audit Log',
        labelKey: 'header.auditLog',
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
  '/monitors': { icon: Activity, label: 'Monitors', labelKey: 'header.monitors' },
  '/external-nodes': { icon: Cloud, label: 'External', labelKey: 'header.external' },
  '/storage': { icon: HardDrive, label: 'Storage', labelKey: 'header.storage' },
  '/map': { icon: Map, label: 'Map', labelKey: 'header.map' },
  '/discovery': { icon: ScanSearch, label: 'Discovery', labelKey: 'header.discovery' },
  '/agents': { icon: Satellite, label: 'Agents', labelKey: 'header.agents' },
  '/docs': { icon: BookOpen, label: 'Docs', labelKey: 'header.docs' },
  '/logs': { icon: ScrollText, label: 'Logs', labelKey: 'header.logs' },
  '/settings': { icon: Settings, label: 'Settings', labelKey: 'header.settings' },
  '/ipam': { icon: Globe, label: 'IPAM', labelKey: 'header.ipam' },
  '/intel': { icon: TrendingUp, label: 'Intel', labelKey: 'header.intel' },

  '/privacy': { icon: ShieldCheck, label: 'Privacy', labelKey: 'header.privacy' },
  '/certificates': { icon: Shield, label: 'Certificates', labelKey: 'header.certificates' },
  '/notifications': { icon: Bell, label: 'Notifications', labelKey: 'header.notifications' },
  '/admin/users': { icon: Users, label: 'Users', labelKey: 'header.users' },
};

/**
 * Default dock item order — used when user has no saved preference.
 */
export const DEFAULT_ORDER = [
  '/discovery',
  '/agents',
  '/map',
  '/hardware',
  '/compute-units',
  '/services',
  '/monitors',
  '/storage',
  '/external-nodes',
  '/ipam',
  '/intel',

  '/privacy',
  '/certificates',
  '/notifications',

  '/docs',
  '/logs',
  '/settings',
];

// Re-export the grip icon for Dock's reorder button
export { GripHorizontal };
