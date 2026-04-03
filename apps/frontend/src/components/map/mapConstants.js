/**
 * Shared map constants — node styles, edge colors, icon resolution, entity
 * field definitions, API mutation maps, and boundary presets.
 *
 * Extracted from MapPage.jsx so BulkPreviewMap (and other consumers) can
 * reference the same visual vocabulary without importing the full page.
 */

import { getIconEntry } from '../common/IconPickerModal';
import { getVendorIcon } from '../../icons/vendorIcons';
import {
  Router,
  Network,
  Shield,
  Wifi,
  Database,
  BatteryCharging,
  Zap,
  Cpu,
  Server,
  Monitor,
  Cctv,
  Tv,
  PcCase,
  Laptop,
  Smartphone,
  Cloud,
  Printer,
  HardDrive,
  Thermometer,
  Gamepad2,
  Phone,
  Tablet,
  Box,
} from 'lucide-react';
import {
  clustersApi,
  hardwareApi,
  computeUnitsApi,
  servicesApi,
  storageApi,
  networksApi,
  miscApi,
  externalNodesApi,
} from '../../api/client';

// ── Node Styles ─────────────────────────────────────────────────────────────
export const NODE_STYLES = new Map([
  ['cluster', { background: '#7c3aed', borderColor: '#5b21b6', glowColor: '#a78bfa' }],
  ['hardware', { background: '#4a7fa5', borderColor: '#2c5f7a', glowColor: '#4a7fa5' }],
  ['compute', { background: '#3a7d44', borderColor: '#1f5c2c', glowColor: '#3a7d44' }],
  ['service', { background: '#c2601e', borderColor: '#8f4012', glowColor: '#e07030' }],
  ['storage', { background: '#7b4fa0', borderColor: '#5a3278', glowColor: '#7b4fa0' }],
  ['network', { background: '#0e8a8a', borderColor: '#0a6060', glowColor: '#0eb8b8' }],
  ['misc', { background: '#4a5568', borderColor: '#2d3748', glowColor: '#6b7a96' }],
  ['external', { background: '#2196f3', borderColor: '#1565c0', glowColor: '#64b5f6' }],
  ['docker_network', { background: '#0b6e8e', borderColor: '#086080', glowColor: '#1cb8d8' }],
  ['docker_container', { background: '#1e6ba8', borderColor: '#164e80', glowColor: '#2d8ae0' }],
]);

// Per-relation edge accent colours — peers_with tracks the theme primary
export const EDGE_COLORS = new Map([
  ['hosts', '#4a7fa5'],
  ['runs', '#3a7d44'],
  ['connects_to', '#0eb8b8'],
  ['depends_on', '#e07030'],
  ['uses', '#7b4fa0'],
  ['integrates_with', '#6b7a96'],
  ['routes', '#ff6b35'],
  ['on_network', '#00d4aa'],
  ['has_storage', '#c47a2a'],
  ['cluster_member', '#a78bfa'],
]);

// ── Device icon map — role/device_type → Lucide component ───────────────────
export const DEVICE_ICON_MAP = {
  // From role
  router: Router,
  switch: Network,
  firewall: Shield,
  access_point: Wifi,
  nas: Database,
  ups: BatteryCharging,
  pdu: Zap,
  sbc: Cpu,
  hypervisor: Server,
  storage: Database,
  server: Server,
  compute: Monitor,
  // From device_type (scan result — more specific)
  ip_camera: Cctv,
  smart_tv: Tv,
  windows_pc: PcCase,
  linux_server: Server,
  printer: Printer,
  iot_device: Cpu,
  desktop: PcCase,
  laptop: Laptop,
  tablet: Tablet,
  phone: Smartphone,
  voip_phone: Phone,
  cloud: Cloud,
  database: Database,
  workstation: PcCase,
  mini_pc: PcCase,
  raspberry_pi: Cpu,
  thermostat: Thermometer,
  gaming_console: Gamepad2,
  vm: Monitor,
  lxc: Box,
  // Fallback
  default: HardDrive,
};

/**
 * Returns the Lucide icon component for a hardware node.
 * Priority: device_type (scan result) → role → HardDrive fallback.
 */
export function resolveDeviceIcon(nodeData) {
  // Manual override from Node Icon picker takes highest priority
  if (nodeData.nodeShape && DEVICE_ICON_MAP[nodeData.nodeShape]) {
    return DEVICE_ICON_MAP[nodeData.nodeShape];
  }
  if (nodeData.device_type && DEVICE_ICON_MAP[nodeData.device_type]) {
    return DEVICE_ICON_MAP[nodeData.device_type];
  }
  if (nodeData.role && DEVICE_ICON_MAP[nodeData.role]) {
    return DEVICE_ICON_MAP[nodeData.role];
  }
  return DEVICE_ICON_MAP.default;
}

export function getEdgeColor(relation) {
  if (relation === 'peers_with') {
    return (
      getComputedStyle(document.documentElement).getPropertyValue('--color-primary').trim() ||
      '#fe8019'
    );
  }
  return EDGE_COLORS.get(relation) || '#6c7086';
}

export const NODE_TYPE_LABELS = new Map([
  ['cluster', 'Cluster'],
  ['hardware', 'Hardware'],
  ['compute', 'Compute'],
  ['service', 'Service'],
  ['storage', 'Storage'],
  ['network', 'Network'],
  ['misc', 'Misc'],
  ['external', 'External'],
  ['docker_network', 'Docker Net'],
  ['docker_container', 'Container'],
]);

// Node types shown as individual toggle chips in the "Show:" bar.
// Docker sub-types (docker_network / docker_container) are controlled via the
// single 'docker' include key and rendered separately, so we exclude them here.
export const FILTER_NODE_TYPES = Array.from(NODE_STYLES.keys()).filter(
  (t) => t !== 'docker_network' && t !== 'docker_container'
);

export const CONNECTION_TYPE_LEGEND = [
  { key: 'ethernet', label: '🔌 Ethernet', color: '#32b89e' },
  { key: 'wireless', label: '📶 Wireless', color: '#7c5cbf' },
  { key: 'tunnel', label: '🕳️ Tunnel', color: '#e68161' },
  { key: 'ssh', label: '🛡️ SSH', color: '#32b89e' },
  { key: 'wg', label: '🔒 WireGuard', color: '#c01521' },
  { key: 'vpn', label: '🌐 VPN', color: '#2074c2' },
];

export const STATUS_LEGEND = [
  { key: 'active', label: 'Active', color: '#32b89e' },
  { key: 'warning', label: 'Warning', color: '#e68161' },
  { key: 'error', label: 'Error', color: '#ff5459' },
];

// Map node type → page route for "Open in HUD"
export const NODE_TYPE_ROUTES = new Map([
  ['cluster', '/hardware'],
  ['hardware', '/hardware'],
  ['compute', '/compute-units'],
  ['service', '/services'],
  ['storage', '/storage'],
  ['network', '/networks'],
  ['misc', '/misc'],
  ['external', '/external-nodes'],
]);

export const BASE_NODE_STYLE = {
  background: 'transparent',
  border: 'none',
  boxShadow: 'none',
  padding: 0,
  width: 140,
};

// ── Icon Resolution ──────────────────────────────────────────────────────────

const KIND_ICON = new Map([
  ['disk', 'hdd'],
  ['pool', 'nas'],
  ['dataset', 'nas'],
  ['share', 'nas'],
  ['container', 'docker'],
]);

const ROLE_ICON = new Map([
  ['router', 'router'],
  ['firewall', 'firewall'],
  ['switch', 'switch'],
  ['ap', 'switch'],
  ['nas', 'nas'],
]);

export function resolveNodeIcon(type, icon_slug, vendor, kind, role, clusterType) {
  if (
    icon_slug &&
    (icon_slug.startsWith('/') ||
      icon_slug.startsWith('http://') ||
      icon_slug.startsWith('https://'))
  ) {
    return icon_slug;
  }
  if (
    icon_slug &&
    typeof icon_slug === 'string' &&
    (/^[a-zA-Z0-9_.-]+$/.test(icon_slug) || icon_slug.startsWith('user-'))
  ) {
    const iconEntry = getIconEntry(icon_slug);
    return iconEntry?.path ?? null;
  }
  if (type === 'hardware' && ROLE_ICON.has(role)) {
    return getIconEntry(ROLE_ICON.get(role))?.path ?? null;
  }
  if (type === 'hardware' && vendor) return getVendorIcon(vendor)?.path ?? null;
  if (type === 'cluster' && clusterType === 'proxmox') {
    return getVendorIcon('proxmox')?.path ?? getIconEntry('cluster')?.path ?? null;
  }
  if (type === 'network') return getIconEntry('network')?.path ?? null;
  if (kind && KIND_ICON.has(kind)) {
    return getIconEntry(KIND_ICON.get(kind))?.path ?? null;
  }
  if (type === 'external') return getIconEntry('internet')?.path ?? null;
  return null;
}

// ── Entity field definitions for the sidebar ────────────────────────────────
export const ENTITY_FIELDS = new Map([
  [
    'hardware',
    [
      { key: 'role', label: 'Role' },
      { key: 'vendor', label: 'Vendor' },
      { key: 'model', label: 'Model' },
      { key: 'ip_address', label: 'IP Address' },
      { key: 'wan_uplink', label: 'WAN / Uplink' },
      { key: 'cpu', label: 'CPU' },
      { key: 'memory_gb', label: 'Memory', fmt: (v) => `${v} GB` },
      { key: 'location', label: 'Location' },
      { key: 'notes', label: 'Notes' },
    ],
  ],
  [
    'compute',
    [
      { key: 'kind', label: 'Kind' },
      { key: 'os', label: 'OS' },
      { key: 'ip_address', label: 'IP Address' },
      { key: 'cpu_cores', label: 'CPU Cores' },
      { key: 'memory_mb', label: 'Memory', fmt: (v) => `${v} MB` },
      { key: 'disk_gb', label: 'Disk', fmt: (v) => `${v} GB` },
      { key: 'environment', label: 'Env' },
      { key: 'notes', label: 'Notes' },
    ],
  ],
  [
    'service',
    [
      { key: 'slug', label: 'Slug' },
      { key: 'category', label: 'Category' },
      { key: 'status', label: 'Status' },
      { key: 'ip_address', label: 'IP Address' },
      { key: 'url', label: 'URL' },
      {
        key: 'ports',
        label: 'Ports',
        fmt: (v) =>
          Array.isArray(v)
            ? v
                .map((p) => (p.port ? `${p.port}/${p.protocol || 'tcp'}` : '—'))
                .filter(Boolean)
                .join(', ') || '—'
            : String(v ?? '—'),
      },
      { key: 'environment', label: 'Env' },
      { key: 'description', label: 'Description' },
    ],
  ],
  [
    'storage',
    [
      { key: 'kind', label: 'Kind' },
      { key: 'capacity_gb', label: 'Capacity', fmt: (v) => `${v} GB` },
      { key: 'path', label: 'Path' },
      { key: 'protocol', label: 'Protocol' },
      { key: 'notes', label: 'Notes' },
    ],
  ],
  [
    'network',
    [
      { key: 'cidr', label: 'CIDR' },
      { key: 'vlan_id', label: 'VLAN ID' },
      { key: 'gateway', label: 'Gateway' },
      { key: 'description', label: 'Description' },
    ],
  ],
  [
    'misc',
    [
      { key: 'kind', label: 'Kind' },
      { key: 'url', label: 'URL' },
      { key: 'description', label: 'Description' },
    ],
  ],
  [
    'cluster',
    [
      { key: 'description', label: 'Description' },
      { key: 'environment', label: 'Env' },
      { key: 'location', label: 'Location' },
      { key: 'member_count', label: 'Members' },
    ],
  ],
  [
    'external',
    [
      { key: 'provider', label: 'Provider' },
      { key: 'kind', label: 'Kind' },
      { key: 'region', label: 'Region' },
      { key: 'ip_address', label: 'IP Address' },
      { key: 'environment', label: 'Environment' },
      { key: 'notes', label: 'Notes' },
    ],
  ],
]);

// ── Entity API mutation maps ─────────────────────────────────────────────────
export const ENTITY_API_UPDATE_ICON = new Map([
  ['cluster', (id, slug) => clustersApi.update(id, { icon_slug: slug })],
  ['hardware', (id, slug) => hardwareApi.update(id, { vendor_icon_slug: slug })],
  ['compute', (id, slug) => computeUnitsApi.update(id, { icon_slug: slug })],
  ['service', (id, slug) => servicesApi.update(id, { icon_slug: slug })],
  ['storage', (id, slug) => storageApi.update(id, { icon_slug: slug })],
  ['network', (id, slug) => networksApi.update(id, { icon_slug: slug })],
  ['misc', (id, slug) => miscApi.update(id, { icon_slug: slug })],
  ['external', (id, slug) => externalNodesApi.update(id, { icon_slug: slug })],
]);

export const ENTITY_API_UPDATE_STATUS = new Map([
  ['hardware', (id, val) => hardwareApi.update(id, { status_override: val || null })],
  ['compute', (id, val) => computeUnitsApi.update(id, { status_override: val || null })],
  ['service', (id, val) => servicesApi.update(id, { status: val || 'running' })],
]);

export const ENTITY_API_UPDATE_ALIAS = new Map([
  ['cluster', (id, name) => clustersApi.update(id, { name })],
  ['hardware', (id, name) => hardwareApi.update(id, { name })],
  ['compute', (id, name) => computeUnitsApi.update(id, { name })],
  ['service', (id, name) => servicesApi.update(id, { name })],
  ['storage', (id, name) => storageApi.update(id, { name })],
  ['network', (id, name) => networksApi.update(id, { name })],
  ['misc', (id, name) => miscApi.update(id, { name })],
  ['external', (id, name) => externalNodesApi.update(id, { name })],
]);

export const ENTITY_API_DELETE = new Map([
  ['cluster', (id) => clustersApi.delete(id)],
  ['hardware', (id) => hardwareApi.delete(id)],
  ['compute', (id) => computeUnitsApi.delete(id)],
  ['service', (id) => servicesApi.delete(id)],
  ['storage', (id) => storageApi.delete(id)],
  ['network', (id) => networksApi.delete(id)],
  ['misc', (id) => miscApi.delete(id)],
  ['external', (id) => externalNodesApi.delete(id)],
]);

export const STATUS_OPTIONS_BY_TYPE = new Map([
  ['hardware', ['auto', 'online', 'offline', 'degraded', 'maintenance']],
  ['compute', ['auto', 'running', 'stopped', 'degraded', 'maintenance']],
  ['service', ['running', 'stopped', 'degraded', 'maintenance']],
]);

export const STATUS_OPTION_LABEL = new Map([
  ['auto', '🧭 Auto (derived)'],
  ['online', '🟢 Online'],
  ['offline', '🔴 Offline'],
  ['degraded', '🟠 Degraded'],
  ['maintenance', '🛠️ Maintenance'],
  ['running', '🟢 Running'],
  ['stopped', '⏹️ Stopped'],
]);

// ── Boundary constants & helpers ─────────────────────────────────────────────
export const BOUNDARY_PRESETS = [
  { key: 'blue', label: 'Blue', stroke: 'rgba(95, 205, 255, 0.75)', fill: [70, 170, 220] },
  { key: 'cyan', label: 'Cyan', stroke: 'rgba(0, 210, 200, 0.75)', fill: [0, 190, 180] },
  { key: 'green', label: 'Green', stroke: 'rgba(80, 200, 100, 0.75)', fill: [60, 180, 80] },
  { key: 'yellow', label: 'Yellow', stroke: 'rgba(230, 200, 50, 0.75)', fill: [210, 180, 40] },
  { key: 'orange', label: 'Orange', stroke: 'rgba(240, 150, 50, 0.75)', fill: [220, 130, 40] },
  { key: 'red', label: 'Red', stroke: 'rgba(230, 80, 80, 0.75)', fill: [210, 60, 60] },
  { key: 'purple', label: 'Purple', stroke: 'rgba(170, 110, 220, 0.75)', fill: [150, 90, 200] },
  { key: 'gray', label: 'Gray', stroke: 'rgba(160, 170, 180, 0.75)', fill: [140, 150, 160] },
];

export const DEFAULT_BOUNDARY_COLOR = 'blue';
export const DEFAULT_BOUNDARY_FILL_OPACITY = 0.12;

export function resolveBoundaryPreset(colorKey) {
  return BOUNDARY_PRESETS.find((p) => p.key === colorKey) || BOUNDARY_PRESETS[0];
}

export function boundaryFillString(preset, opacity) {
  const [r, g, b] = preset.fill;
  return `rgba(${r}, ${g}, ${b}, ${opacity})`;
}

export const LEGACY_LABEL_COLOR_MAP = new Map([
  ['yellow', 'yellow'],
  ['blue', 'blue'],
  ['green', 'green'],
  ['pink', 'red'],
  ['gray', 'gray'],
]);

export function normalizeBoundaryName(name, index) {
  const trimmed = String(name || '').trim();
  return trimmed || `Boundary ${index + 1}`;
}

export function normalizeMapLabel(label, index) {
  const rawColor = String(label?.color || 'blue');
  const color = LEGACY_LABEL_COLOR_MAP.get(rawColor) || rawColor;
  const validKeys = BOUNDARY_PRESETS.map((p) => p.key);
  return {
    id: String(label?.id || `map-label-${Date.now()}-${index}`),
    text: String(label?.text || '').trim() || 'Label',
    x: Number.isFinite(label?.x) ? Number(label.x) : 160,
    y: Number.isFinite(label?.y) ? Number(label.y) : 160,
    width: Math.max(140, Number(label?.width) || 220),
    height: Math.max(48, Number(label?.height) || 48),
    color: validKeys.includes(color) ? color : 'blue',
  };
}

export const BOUNDARY_SHAPES = [
  { key: 'rectangle', label: 'Rectangle', icon: '▭' },
  { key: 'rounded', label: 'Rounded', icon: '▢' },
  { key: 'ellipse', label: 'Ellipse', icon: '⬭' },
];
